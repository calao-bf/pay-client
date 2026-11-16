/* Composant de paiement de pay-client : le payeur reste sur la page de l'application.
 *
 * Il ne parle qu'au serveur de l'application (les vues de pay_client.composant), jamais à Pay.
 * Il affiche ce que Pay demande (`next_action`) : message USSD, saisie du code OTP, Payment
 * Element de Stripe, bouton PayPal ; puis le statut, à la seconde.
 *
 * Événement émis sur le bloc : `pay:statut` (detail = le paiement) à chaque changement.
 * Classes CSS : .pay-paiement, .pay-texte, .pay-erreur, .pay-moyens, .pay-bouton,
 * .pay-champ, .pay-carte, .pay-lien.
 */
(function () {
  "use strict";

  var STRIPE_JS = "https://js.stripe.com/v3/";
  // developer.paypal.com/sdk/js/set-up (lu le 2026-11-16).
  var PAYPAL_JS = {
    live: "https://www.paypal.com/web-sdk/v6/core",
    sandbox: "https://www.sandbox.paypal.com/web-sdk/v6/core",
  };
  var NOMS = {
    moov_money: "Moov Money",
    orange_money: "Orange Money",
    card: "Carte bancaire",
    paypal: "PayPal",
  };
  var AVEC_TELEPHONE = ["moov_money", "orange_money"];
  var EN_COURS = ["created", "pending"];
  var PATIENCE_MS = 120000; // au-delà : « vous serez prévenu »

  function el(balise, classe, texte) {
    var n = document.createElement(balise);
    if (classe) n.className = classe;
    if (texte) n.textContent = texte;
    return n;
  }

  // `present` : le script est déjà là (chargé par la page elle-même, par exemple).
  function charger(src, present) {
    return new Promise(function (ok, ko) {
      if (present()) return ok();
      var deja = document.querySelector('script[src="' + src + '"]');
      var s = deja || el("script");
      s.addEventListener("load", function () { ok(); });
      s.addEventListener("error", function () { ko(new Error("Chargement impossible : " + src)); });
      if (!deja) { s.src = src; s.async = true; document.head.appendChild(s); }
    });
  }

  function montant(valeur, devise) {
    var f = new Intl.NumberFormat("fr-FR", { style: "currency", currency: devise });
    var decimales = f.resolvedOptions().maximumFractionDigits;
    return f.format(valeur / Math.pow(10, decimales));
  }

  // Numéro du payeur au format E.164 ; 8 chiffres seuls : Burkina Faso (+226).
  function telephone(saisie) {
    var t = (saisie || "").replace(/[\s.\-()]/g, "");
    if (t.indexOf("00") === 0) t = "+" + t.slice(2);
    if (/^\d{8}$/.test(t)) t = "+226" + t;
    return t;
  }

  function Composant(bloc) {
    this.bloc = bloc;
    this.adresse = bloc.dataset.adresse;
    this.csrf = bloc.dataset.csrf;
    this.suite = bloc.dataset.suite;
    this.suivi = 0; // jeton du suivi en cours (un seul à la fois)
    this.depart();
  }

  Composant.prototype.appel = function (methode, chemin, corps) {
    var options = { method: methode, credentials: "same-origin", headers: { Accept: "application/json" } };
    if (methode === "POST") {
      options.headers["Content-Type"] = "application/json";
      options.headers["X-CSRFToken"] = this.csrf;
      options.body = JSON.stringify(corps || {});
    }
    return fetch(this.adresse + chemin, options).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (donnees) {
        if (r.ok) return donnees;
        var e = new Error((donnees.error && donnees.error.message) || "Erreur " + r.status + ".");
        e.code = donnees.error && donnees.error.code;
        e.status = r.status;
        throw e;
      });
    });
  };

  Composant.prototype.vider = function () {
    this.bloc.textContent = "";
    return this.bloc;
  };

  Composant.prototype.texte = function (message, classe) {
    var p = el("p", classe || "pay-texte", message);
    this.bloc.appendChild(p);
    return p;
  };

  Composant.prototype.panne = function (erreur, retour) {
    var soi = this;
    this.texte(erreur.message || "Le paiement est momentanément indisponible.", "pay-erreur");
    var b = el("button", "pay-bouton", retour ? "Choisir un autre moyen" : "Réessayer");
    b.type = "button";
    b.addEventListener("click", function () { soi.depart(); });
    this.bloc.appendChild(b);
  };

  Composant.prototype.depart = function () {
    var soi = this;
    this.suivi += 1;
    this.vider();
    this.texte("Chargement du paiement…");
    this.appel("GET", "").then(function (etat) {
      soi.etat = etat;
      if (etat.payment) soi.afficher(etat.payment);
      else soi.choix();
    }, function (e) { soi.vider(); soi.panne(e); });
  };

  // ---------------------------------------------------------------- choix du moyen
  Composant.prototype.choix = function () {
    var soi = this, etat = this.etat;
    this.vider();
    this.texte("Montant à payer : " + montant(etat.amount, etat.currency));
    if (!etat.methods.length) {
      this.texte("Aucun moyen de paiement n'est disponible pour le moment. Réessayez plus tard.", "pay-erreur");
      return;
    }
    var champ = el("input", "pay-champ");
    champ.type = "tel";
    champ.autocomplete = "tel";
    champ.placeholder = "Numéro du payeur, ex. 70 00 00 00";
    champ.value = etat.phone || "";
    var libelle = el("label", "pay-texte", "Numéro Mobile Money ");
    libelle.appendChild(champ);
    libelle.hidden = true;
    var moyens = el("div", "pay-moyens");
    etat.methods.forEach(function (m) {
      var b = el("button", "pay-bouton", NOMS[m] || m);
      b.type = "button";
      b.addEventListener("click", function () {
        if (AVEC_TELEPHONE.indexOf(m) >= 0 && !telephone(champ.value)) {
          libelle.hidden = false;
          champ.focus();
          champ.dataset.moyen = m;
          return;
        }
        soi.payer(m, AVEC_TELEPHONE.indexOf(m) >= 0 ? telephone(champ.value) : "");
      });
      moyens.appendChild(b);
    });
    champ.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && champ.dataset.moyen) soi.payer(champ.dataset.moyen, telephone(champ.value));
    });
    this.bloc.appendChild(moyens);
    this.bloc.appendChild(libelle);
    if (champ.value === "" && etat.methods.some(function (m) { return AVEC_TELEPHONE.indexOf(m) >= 0; })) {
      libelle.hidden = false;
    }
  };

  Composant.prototype.payer = function (moyen, numero) {
    var soi = this;
    this.vider();
    this.texte("Préparation du paiement…");
    this.appel("POST", "payer/", { method: moyen, phone: numero }).then(
      function (p) { soi.afficher(p); },
      function (e) { soi.vider(); soi.panne(e, true); }
    );
  };

  // ---------------------------------------------------------------- un paiement
  Composant.prototype.afficher = function (p) {
    this.paiement = p;
    this.bloc.dispatchEvent(new CustomEvent("pay:statut", { detail: p, bubbles: true }));
    this.vider();
    if (EN_COURS.indexOf(p.status) < 0) return this.fin(p);
    var action = p.next_action || { type: "none" };
    this.texte("Montant : " + montant(p.amount, p.currency));
    if (action.type === "otp_input") this.otp(p, action);
    else if (action.type === "card_form") this.carte(p, action);
    else if (action.type === "paypal_buttons") this.paypal(p, action);
    else if (action.message) this.texte(action.message);
    else this.texte("Paiement en cours…");
    this.zoneAttente = this.texte("", "pay-texte");
    if (action.type !== "card_form" && action.type !== "paypal_buttons") this.changer(p);
    this.attendre(p);
  };

  // Abandonner un paiement en attente pour choisir un autre moyen.
  Composant.prototype.changer = function (p) {
    var soi = this;
    var b = el("button", "pay-lien", "Changer de moyen de paiement");
    b.type = "button";
    b.addEventListener("click", function () {
      b.disabled = true;
      soi.suivi += 1;
      soi.appel("POST", "paiements/" + encodeURIComponent(p.id) + "/annuler/").then(
        function () { soi.depart(); },
        function () { soi.depart(); }
      );
    });
    this.bloc.appendChild(b);
  };

  Composant.prototype.otp = function (p, action) {
    var soi = this;
    if (action.message) this.texte(action.message);
    if (action.ussd_code) {
      var lien = el("a", "pay-lien", "Composer " + action.ussd_code);
      lien.href = "tel:" + encodeURIComponent(action.ussd_code);
      this.bloc.appendChild(lien);
    }
    var forme = el("form", "pay-otp");
    var champ = el("input", "pay-champ");
    champ.inputMode = "numeric";
    champ.autocomplete = "one-time-code";
    champ.placeholder = "Code reçu par SMS";
    champ.required = true;
    var b = el("button", "pay-bouton", "Valider le code");
    b.type = "submit";
    var erreur = el("p", "pay-erreur");
    forme.appendChild(champ);
    forme.appendChild(b);
    forme.appendChild(erreur);
    forme.addEventListener("submit", function (ev) {
      ev.preventDefault();
      b.disabled = true;
      erreur.textContent = "";
      soi.appel("POST", "paiements/" + encodeURIComponent(p.id) + "/confirmer/", { otp: champ.value.trim() }).then(
        function (lu) { if (EN_COURS.indexOf(lu.status) < 0) soi.afficher(lu); else b.disabled = false; },
        function (e) { erreur.textContent = e.message; b.disabled = false; }
      );
    });
    this.bloc.appendChild(forme);
  };

  Composant.prototype.carte = function (p, action) {
    var soi = this;
    var zone = el("div", "pay-carte");
    var b = el("button", "pay-bouton", "Payer " + montant(p.amount, p.currency));
    b.type = "button";
    b.disabled = true;
    var erreur = el("p", "pay-erreur");
    this.bloc.appendChild(zone);
    this.bloc.appendChild(b);
    this.bloc.appendChild(erreur);
    // Retour de la banque (3-D Secure) : Stripe a ajouté `payment_intent` à l'adresse ; le
    // statut arrive par le suivi, sans remontrer le formulaire.
    if (/[?&]payment_intent=/.test(window.location.search)) {
      zone.remove();
      b.remove();
      this.zoneAttente = this.texte("Vérification du paiement…");
      return;
    }
    if (!action.client_secret) {
      erreur.textContent = "Rechargez la page pour reprendre le paiement par carte.";
      return;
    }
    charger(STRIPE_JS, function () { return !!window.Stripe; }).then(function () {
      var stripe = window.Stripe(action.publishable_key);
      var elements = stripe.elements({ clientSecret: action.client_secret });
      elements.create("payment").mount(zone);
      b.disabled = false;
      b.addEventListener("click", function () {
        b.disabled = true;
        erreur.textContent = "";
        stripe.confirmPayment({
          elements: elements,
          // Seulement si la banque l'exige : le composant reprend le paiement au retour.
          confirmParams: { return_url: window.location.href },
          redirect: "if_required",
        }).then(function (r) {
          if (r.error) { erreur.textContent = r.error.message; b.disabled = false; }
          else soi.zoneAttente.textContent = "Vérification du paiement…";
        });
      });
    }, function (e) { erreur.textContent = e.message; });
  };

  Composant.prototype.paypal = function (p, action) {
    var soi = this;
    var erreur = el("p", "pay-erreur");
    var bouton = el("paypal-button");
    bouton.setAttribute("type", "pay");
    bouton.hidden = true;
    this.bloc.appendChild(bouton);
    this.bloc.appendChild(erreur);
    charger(p.livemode ? PAYPAL_JS.live : PAYPAL_JS.sandbox, function () {
      return !!(window.paypal && window.paypal.createInstance);
    }).then(function () {
      return window.paypal.createInstance({
        clientId: action.client_id,
        components: ["paypal-payments"],
        pageType: "checkout",
      });
    }).then(function (sdk) {
      return sdk.findEligibleMethods().then(function (moyens) {
        if (!moyens.isEligible("paypal")) throw new Error("PayPal n'est pas disponible ici.");
        var session = sdk.createPayPalOneTimePaymentSession({
          onApprove: function () {
            soi.zoneAttente.textContent = "Encaissement…";
            return soi.appel("POST", "paiements/" + encodeURIComponent(p.id) + "/confirmer/").then(
              function (lu) { if (EN_COURS.indexOf(lu.status) < 0) soi.afficher(lu); },
              function (e) { erreur.textContent = e.message; }
            );
          },
          onCancel: function () { erreur.textContent = "Paiement PayPal interrompu : vous pouvez recommencer."; },
          onError: function () { erreur.textContent = "PayPal a rencontré une erreur : réessayez."; },
        });
        bouton.hidden = false;
        bouton.addEventListener("click", function () {
          erreur.textContent = "";
          session.start({ presentationMode: "auto" }, Promise.resolve({ orderId: action.order_id }));
        });
      });
    }).catch(function (e) { erreur.textContent = e.message; });
  };

  // ---------------------------------------------------------------- statut en direct
  Composant.prototype.attendre = function (p) {
    var soi = this, jeton = ++this.suivi, debut = Date.now();
    function tour() {
      if (jeton !== soi.suivi) return;
      soi.appel("GET", "paiements/" + encodeURIComponent(p.id) + "/?attendre=1").then(function (lu) {
        if (jeton !== soi.suivi) return;
        if (EN_COURS.indexOf(lu.status) < 0) return soi.afficher(lu);
        if (Date.now() - debut > PATIENCE_MS) {
          soi.zoneAttente.textContent = "Paiement en cours de vérification : vous serez prévenu dès sa confirmation.";
        }
        tour();
      }, function () {
        if (jeton === soi.suivi) setTimeout(tour, 3000);
      });
    }
    tour();
  };

  Composant.prototype.fin = function (p) {
    var soi = this;
    this.suivi += 1;
    if (p.status === "succeeded" || p.status === "partially_refunded" || p.status === "refunded") {
      this.texte(p.status === "succeeded" ? "Paiement reçu. Merci !" : "Cette commande a déjà été payée.");
      if (this.suite && p.status === "succeeded") {
        setTimeout(function () { window.location.assign(soi.suite); }, 1500);
      }
      return;
    }
    var raison = p.failure && p.failure.message;
    this.panne({ message: (p.status === "expired" ? "Le délai de paiement est dépassé." : "Le paiement n'a pas abouti.") + (raison ? " " + raison : "") }, true);
  };

  function demarrer() {
    document.querySelectorAll(".pay-paiement:not([data-pret])").forEach(function (bloc) {
      bloc.dataset.pret = "1";
      new Composant(bloc);
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", demarrer);
  else demarrer();
})();

/* Inline questions and errors — the replacement for every native alert()/confirm() in the app.
   Chunk 6.7 (2026-10-06); approved mockups: docs/mockups/chunk-6.7/popups.html; the rule and the
   "which one to use when" catalogue: docs/ui-ux.md > "No native dialogs".

   WHY: the browser's own dialogs are clunky, can't say what a button does (OK/Cancel), hide the
   page, and on a phone show the server's raw address in their title. Everything is now asked and
   reported inline, in plain words, right where it happened.

   Three tools, chosen by where the user was looking:
     * Feedback.error(slot, message, {retry, box})  — an error NEXT TO the thing that failed. A short
       red line by default (a row you tapped, a button, a field); {box: true} for a boxed notice when
       a whole section failed. {retry: fn} adds a "Retry" button. One error per slot; a new call
       replaces the old one; Feedback.clear(slot) removes it.
     * Feedback.card(host, {title, body, tone, confirmLabel, cancelLabel, onConfirm, onCancel}) — a
       question that needs a decision, as a card inserted right after `host`. Buttons are named for
       what they do (never OK/Cancel); focus moves to the first button; Escape = the cancel action.
     * Toast.show(msg, {tone: "error", actionLabel, onAction}) — for an error where the thing you
       tapped is already gone (e.g. an Undo that failed): see toast.js.

   Rules: every error is announced (role=alert); nothing blocks the page; no layout jump beyond the
   inserted line/card; tap targets stay >=44px (the existing button styles). */

(function (global) {
  "use strict";

  var MARK = "data-inline-feedback";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function clear(slot) {
    if (!slot) return;
    Array.prototype.slice.call(slot.querySelectorAll("[" + MARK + "]")).forEach(function (n) {
      if (n.parentNode) n.parentNode.removeChild(n);
    });
  }

  function messageOf(err, fallback) {
    if (typeof err === "string") return err;
    return (err && err.message) || fallback || "Something went wrong.";
  }

  function error(slot, message, opts) {
    opts = opts || {};
    if (!slot) return null;
    clear(slot);
    var text = messageOf(message);
    var node;
    if (opts.box) {
      node = el("div", "error-state");
      var body = el("div");
      body.appendChild(el("b", null, text));
      node.appendChild(body);
      if (typeof opts.retry === "function") {
        var actions = el("div", "actions");
        actions.style.marginTop = "8px";
        var retryBox = el("button", "btn-sm primary", opts.retryLabel || "Retry");
        retryBox.type = "button";
        retryBox.addEventListener("click", function () { clear(slot); opts.retry(); });
        actions.appendChild(retryBox);
        body.appendChild(actions);
      }
    } else {
      node = el("span", "form-error", text);
      if (typeof opts.retry === "function") {
        node.appendChild(document.createTextNode(" "));
        var retry = el("button", "btn-link", opts.retryLabel || "Retry");
        retry.type = "button";
        retry.addEventListener("click", function () { clear(slot); opts.retry(); });
        node.appendChild(retry);
      }
    }
    node.setAttribute("role", "alert");
    node.setAttribute(MARK, "error");
    slot.appendChild(node);
    return node;
  }

  /* card(host, opts) — a decision card inserted immediately after `host` (or appended inside it
     with opts.into). Returns {el, remove}. Only one card per host: asking again replaces it. */
  function card(host, opts) {
    opts = opts || {};
    var parent = opts.into ? host : host.parentNode;
    if (!parent) return null;
    Array.prototype.slice.call(parent.querySelectorAll("[" + MARK + '="card"]')).forEach(function (n) {
      if (n.parentNode) n.parentNode.removeChild(n);
    });

    var node = el("div", "inline-card" + (opts.tone === "warn" ? " warn" : ""));
    node.setAttribute("role", "group");
    node.setAttribute("aria-label", opts.title || "Question");
    node.setAttribute(MARK, "card");
    if (opts.title) node.appendChild(el("div", "title", opts.title));
    if (opts.body) node.appendChild(el("div", "body", opts.body));
    var errSlot = el("div");
    node.appendChild(errSlot);

    var actions = el("div", "actions row");
    var confirm = el("button", "primary btn-sm", opts.confirmLabel || "Yes");
    confirm.type = "button";
    var cancel = el("button", "btn-sm", opts.cancelLabel || "Not now");
    cancel.type = "button";
    actions.appendChild(confirm);
    actions.appendChild(cancel);
    node.appendChild(actions);

    function remove() {
      document.removeEventListener("keydown", onKey, true);
      if (node.parentNode) node.parentNode.removeChild(node);
    }
    function onKey(e) {
      if (e.key === "Escape") {
        e.preventDefault();
        remove();
        if (typeof opts.onCancel === "function") opts.onCancel();
      }
    }
    confirm.addEventListener("click", function () {
      remove();
      if (typeof opts.onConfirm === "function") opts.onConfirm();
    });
    cancel.addEventListener("click", function () {
      remove();
      if (typeof opts.onCancel === "function") opts.onCancel();
    });
    document.addEventListener("keydown", onKey, true);

    if (opts.into) parent.appendChild(node);
    else parent.insertBefore(node, host.nextSibling);
    try { confirm.focus({ preventScroll: false }); } catch (_) { /* focus is a nicety */ }
    return { el: node, remove: remove, errorSlot: errSlot };
  }

  global.Feedback = { error: error, clear: clear, card: card, messageOf: messageOf };
})(window);

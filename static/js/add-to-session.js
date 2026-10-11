/* "Add to session" (Phase 6 Chunk 6.2, kickoff decision #2). Split out of recipes.js per
   CLAUDE.md > Code Architecture & Maintainability > file size discipline — recipes.js was
   pushing past the ~400-line guideline once the cuisine filter chips landed alongside this.
   One active session -> add straight to it; several -> a tiny inline picker; none -> offer
   to start one. Currently only called from recipes.js (library card + detail page), but
   kept as its own small file since "add this recipe to whatever session is in progress" is
   a standalone concern, not something specific to the recipe library screen. */

(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  // One feedback holder per host button, inserted right after it: errors and the "start a session?"
  // card appear there (docs/ui-ux.md > No native dialogs). The library row is a full-card <a>, so
  // the holder swallows clicks (preventDefault + stopPropagation, as recipes.js's own button does) or
  // tapping "Retry" / "Not now" would also navigate to the recipe. `flex: 1 0 100%` puts it on its own
  // line in both the library row and the detail header.
  function holderFor(hostEl) {
    var holder = hostEl.nextSibling && hostEl.nextSibling.className === "add-feedback" ? hostEl.nextSibling : null;
    if (!holder) {
      holder = el("div", "add-feedback");
      holder.style.flex = "1 0 100%";
      holder.addEventListener("click", function (ev) { ev.preventDefault(); ev.stopPropagation(); });
      hostEl.parentNode.insertBefore(holder, hostEl.nextSibling);
    }
    return holder;
  }

  function doAdd(sessionId, recipeId, hostEl) {
    var holder = holderFor(hostEl);
    global.Feedback.clear(holder);
    return api.sessions
      .addRecipe(sessionId, { recipe_id: recipeId })
      .then(function () {
        hostEl.disabled = false;
        global.Toast.show("Added to session", {
          actionLabel: "View",
          onAction: function () {
            global.Router.navigate("plan", sessionId);
          },
        });
        return true;
      })
      .catch(function (err) {
        hostEl.disabled = false;
        global.Feedback.error(holder, "Couldn't add to session — " + global.Feedback.messageOf(err), {
          retry: function () { doAdd(sessionId, recipeId, hostEl); },
        });
        return false;
      });
  }

  function showSessionPicker(afterEl, sessions, recipeId) {
    var wrap = el("div", "log-controls");
    wrap.style.marginTop = "6px";
    var select = el("select");
    sessions.forEach(function (s) {
      var opt = el("option", null, s.label || "Session #" + s.id);
      opt.value = s.id;
      select.appendChild(opt);
    });
    var goBtn = el("button", "btn-sm primary", "Add");
    goBtn.addEventListener("click", function () {
      goBtn.disabled = true;
      doAdd(parseInt(select.value, 10), recipeId, goBtn).then(function (ok) {
        // Only dismiss the picker on success - on failure it sits next to the error and Retry.
        if (ok && wrap.parentNode) wrap.parentNode.removeChild(wrap);
      });
    });
    wrap.appendChild(select);
    wrap.appendChild(goBtn);
    afterEl.parentNode.insertBefore(wrap, afterEl.nextSibling);
  }

  // recipeId: the recipe to add. hostEl: the button that triggered this (disabled while
  // in flight, and the anchor a multi-session picker is inserted after).
  function run(recipeId, hostEl) {
    hostEl.disabled = true;
    global.Feedback.clear(holderFor(hostEl));
    api.sessions
      .list({ status: "active" })
      .then(function (res) {
        var items = res.items || [];
        if (items.length === 1) {
          return doAdd(items[0].id, recipeId, hostEl);
        }
        if (items.length > 1) {
          hostEl.disabled = false;
          showSessionPicker(hostEl, items, recipeId);
          return null;
        }
        hostEl.disabled = false;
        // No native confirm(): an inline card right under the button, buttons named for what they do.
        global.Feedback.card(holderFor(hostEl), {
          into: true,
          title: "No shopping session yet",
          body: "Start one with this recipe in it?",
          confirmLabel: "Start one with this recipe",
          cancelLabel: "Not now",
          onConfirm: function () {
            hostEl.disabled = true;
            api.sessions
              .create({})
              .then(function (s) { return doAdd(s.id, recipeId, hostEl); })
              .catch(function (err) {
                hostEl.disabled = false;
                global.Feedback.error(holderFor(hostEl), "Couldn't start a session — " + global.Feedback.messageOf(err), {
                  retry: function () { run(recipeId, hostEl); },
                });
              });
          },
        });
        return null;
      })
      .catch(function (err) {
        hostEl.disabled = false;
        global.Feedback.error(holderFor(hostEl), "Couldn't check your sessions — " + global.Feedback.messageOf(err), {
          retry: function () { run(recipeId, hostEl); },
        });
      });
  }

  global.AddToSession = { run: run };
})(window);

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

  function doAdd(sessionId, recipeId, hostEl) {
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
      })
      .catch(function (err) {
        hostEl.disabled = false;
        global.alert("Couldn't add to session: " + err.message);
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
      doAdd(parseInt(select.value, 10), recipeId, goBtn).then(function () {
        if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
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
        if (global.confirm("No session in progress yet. Start a new one with this recipe?")) {
          return api.sessions.create({}).then(function (s) {
            return doAdd(s.id, recipeId, hostEl);
          });
        }
        return null;
      })
      .catch(function (err) {
        hostEl.disabled = false;
        global.alert("Couldn't check sessions: " + err.message);
      });
  }

  global.AddToSession = { run: run };
})(window);

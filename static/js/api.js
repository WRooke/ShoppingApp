/* Thin fetch wrapper around the ShoppingApp API.
   Every API response uses the { ok, data } / { ok, error } envelope. */

(function (global) {
  "use strict";

  async function request(path, options) {
    let res;
    try {
      res = await fetch(path, options);
    } catch (networkErr) {
      throw new ApiError(
        "NETWORK_ERROR",
        "Couldn't reach the server. Check that it's running and try again.",
        String(networkErr)
      );
    }

    let body = null;
    try {
      body = await res.json();
    } catch (_) {
      // fall through — handled below
    }

    if (body && body.ok === true) {
      return body.data;
    }

    if (body && body.ok === false && body.error) {
      throw new ApiError(body.error.code, body.error.message, body.error.detail);
    }

    throw new ApiError(
      "BAD_RESPONSE",
      "The server returned an unexpected response (HTTP " + res.status + ").",
      null
    );
  }

  function ApiError(code, message, detail) {
    this.name = "ApiError";
    this.code = code;
    this.message = message;
    this.detail = detail;
  }
  ApiError.prototype = Object.create(Error.prototype);

  function jsonBody(method, path, body) {
    return request(path, {
      method: method,
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
  }

  function formBody(method, path, formData) {
    // No Content-Type header here on purpose — the browser sets the multipart boundary
    // itself; setting it manually breaks the upload.
    return request(path, {
      method: method,
      headers: { Accept: "application/json" },
      body: formData,
    });
  }

  const api = {
    ApiError: ApiError,
    get: function (path) {
      return request(path, { method: "GET", headers: { Accept: "application/json" } });
    },
    health: function () {
      return api.get("/api/v1/health");
    },
    recipes: {
      list: function (params) {
        params = params || {};
        var q = [];
        if (params.search) q.push("search=" + encodeURIComponent(params.search));
        if (params.limit) q.push("limit=" + params.limit);
        if (params.offset) q.push("offset=" + params.offset);
        if (params.includeArchived) q.push("include_archived=true");
        return api.get("/api/v1/recipes" + (q.length ? "?" + q.join("&") : ""));
      },
      get: function (id) {
        return api.get("/api/v1/recipes/" + encodeURIComponent(id));
      },
      create: function (data) {
        return jsonBody("POST", "/api/v1/recipes", data);
      },
      update: function (id, data) {
        return jsonBody("PATCH", "/api/v1/recipes/" + encodeURIComponent(id), data);
      },
      archive: function (id) {
        return request("/api/v1/recipes/" + encodeURIComponent(id), {
          method: "DELETE",
          headers: { Accept: "application/json" },
        });
      },
      restore: function (id) {
        return jsonBody("POST", "/api/v1/recipes/" + encodeURIComponent(id) + "/restore", {});
      },
      checkDuplicate: function (params) {
        params = params || {};
        var q = [];
        ["name", "source_url", "source_book", "source_page", "exclude_id"].forEach(function (k) {
          if (params[k] != null && params[k] !== "") {
            q.push(k + "=" + encodeURIComponent(params[k]));
          }
        });
        return api.get("/api/v1/recipes/check-duplicate?" + q.join("&"));
      },
      addIngredient: function (recipeId, data) {
        return jsonBody(
          "POST",
          "/api/v1/recipes/" + encodeURIComponent(recipeId) + "/ingredients",
          data
        );
      },
      updateIngredient: function (recipeId, ingredientId, data) {
        return jsonBody(
          "PATCH",
          "/api/v1/recipes/" +
            encodeURIComponent(recipeId) +
            "/ingredients/" +
            encodeURIComponent(ingredientId),
          data
        );
      },
      deleteIngredient: function (recipeId, ingredientId) {
        return request(
          "/api/v1/recipes/" +
            encodeURIComponent(recipeId) +
            "/ingredients/" +
            encodeURIComponent(ingredientId),
          { method: "DELETE", headers: { Accept: "application/json" } }
        );
      },
      captureUrl: function (url, allowDuplicate) {
        return jsonBody("POST", "/api/v1/recipes/capture/url", {
          url: url,
          allow_duplicate: !!allowDuplicate,
        });
      },
      capturePhoto: function (file) {
        var formData = new FormData();
        formData.append("image", file);
        return formBody("POST", "/api/v1/recipes/capture/photo", formData);
      },
      confirmCapture: function (data) {
        return jsonBody("POST", "/api/v1/recipes/capture/confirm", data);
      },
    },
    settings: {
      sectionVocabulary: function () {
        return api.get("/api/v1/settings/section-vocabulary");
      },
      staples: {
        list: function () {
          return api.get("/api/v1/settings/staples?limit=200");
        },
        create: function (data) {
          return jsonBody("POST", "/api/v1/settings/staples", data);
        },
        update: function (id, data) {
          return jsonBody("PATCH", "/api/v1/settings/staples/" + encodeURIComponent(id), data);
        },
        delete: function (id) {
          return request("/api/v1/settings/staples/" + encodeURIComponent(id), {
            method: "DELETE",
            headers: { Accept: "application/json" },
          });
        },
      },
      productUnits: {
        list: function () {
          return api.get("/api/v1/settings/product-units?limit=200");
        },
        create: function (data) {
          return jsonBody("POST", "/api/v1/settings/product-units", data);
        },
        update: function (id, data) {
          return jsonBody(
            "PATCH",
            "/api/v1/settings/product-units/" + encodeURIComponent(id),
            data
          );
        },
        delete: function (id) {
          return request("/api/v1/settings/product-units/" + encodeURIComponent(id), {
            method: "DELETE",
            headers: { Accept: "application/json" },
          });
        },
      },
      substitutions: {
        list: function () {
          return api.get("/api/v1/settings/substitutions?limit=500");
        },
        create: function (data) {
          return jsonBody("POST", "/api/v1/settings/substitutions", data);
        },
        update: function (id, data) {
          return jsonBody(
            "PATCH",
            "/api/v1/settings/substitutions/" + encodeURIComponent(id),
            data
          );
        },
        delete: function (id) {
          return request("/api/v1/settings/substitutions/" + encodeURIComponent(id), {
            method: "DELETE",
            headers: { Accept: "application/json" },
          });
        },
      },
      usuals: {
        list: function () {
          return api.get("/api/v1/settings/usuals?limit=200");
        },
        create: function (data) {
          return jsonBody("POST", "/api/v1/settings/usuals", data);
        },
        update: function (id, data) {
          return jsonBody("PATCH", "/api/v1/settings/usuals/" + encodeURIComponent(id), data);
        },
        delete: function (id) {
          return request("/api/v1/settings/usuals/" + encodeURIComponent(id), {
            method: "DELETE",
            headers: { Accept: "application/json" },
          });
        },
      },
    },
    sessions: {
      list: function () {
        return api.get("/api/v1/sessions?limit=100");
      },
      get: function (id) {
        return api.get("/api/v1/sessions/" + encodeURIComponent(id));
      },
      create: function (data) {
        return jsonBody("POST", "/api/v1/sessions", data || {});
      },
      update: function (id, data) {
        return jsonBody("PATCH", "/api/v1/sessions/" + encodeURIComponent(id), data);
      },
      archive: function (id) {
        return jsonBody("POST", "/api/v1/sessions/" + encodeURIComponent(id) + "/archive", {});
      },
      addRecipe: function (id, data) {
        return jsonBody("POST", "/api/v1/sessions/" + encodeURIComponent(id) + "/recipes", data);
      },
      addLeftovers: function (id, data) {
        return jsonBody(
          "POST",
          "/api/v1/sessions/" + encodeURIComponent(id) + "/leftovers",
          data || {}
        );
      },
      updateSlot: function (id, slotId, data) {
        return jsonBody(
          "PATCH",
          "/api/v1/sessions/" + encodeURIComponent(id) + "/slots/" + encodeURIComponent(slotId),
          data
        );
      },
      removeSlot: function (id, slotId) {
        return request(
          "/api/v1/sessions/" +
            encodeURIComponent(id) +
            "/slots/" +
            encodeURIComponent(slotId),
          { method: "DELETE", headers: { Accept: "application/json" } }
        );
      },
      reorder: function (id, orderedIds) {
        return jsonBody(
          "PUT",
          "/api/v1/sessions/" + encodeURIComponent(id) + "/slots/order",
          { ordered_ids: orderedIds }
        );
      },
      consolidate: function (id, overrides) {
        return jsonBody(
          "POST",
          "/api/v1/sessions/" + encodeURIComponent(id) + "/consolidate",
          { overrides: overrides || [] }
        );
      },
    },
    checklist: {
      load: function (sessionId) {
        return api.get("/api/v1/checklist/" + encodeURIComponent(sessionId));
      },
      updateItem: function (sessionId, itemId, data) {
        return jsonBody(
          "PATCH",
          "/api/v1/checklist/" + encodeURIComponent(sessionId) + "/items/" + encodeURIComponent(itemId),
          data
        );
      },
      resolveItem: function (sessionId, itemId, data) {
        return jsonBody(
          "POST",
          "/api/v1/checklist/" +
            encodeURIComponent(sessionId) +
            "/items/" +
            encodeURIComponent(itemId) +
            "/resolve",
          data
        );
      },
      push: function (sessionId, force) {
        return jsonBody(
          "POST",
          "/api/v1/checklist/" +
            encodeURIComponent(sessionId) +
            "/push" +
            (force ? "?force=true" : ""),
          {}
        );
      },
    },
    diagnostics: {
      logs: function (limit, level) {
        let q = "?limit=" + (limit || 200);
        if (level) q += "&level=" + encodeURIComponent(level);
        return api.get("/api/v1/diagnostics/logs" + q);
      },
      recentErrors: function () {
        return api.get("/api/v1/diagnostics/recent-errors");
      },
      status: function () {
        return api.get("/api/v1/diagnostics/status");
      },
    },
  };

  global.api = api;
})(window);

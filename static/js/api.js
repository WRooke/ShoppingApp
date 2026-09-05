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

  const api = {
    ApiError: ApiError,
    get: function (path) {
      return request(path, { method: "GET", headers: { Accept: "application/json" } });
    },
    health: function () {
      return api.get("/api/v1/health");
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

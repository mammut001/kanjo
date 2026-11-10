import { initializeApp } from "https://www.gstatic.com/firebasejs/11.0.0/firebase-app.js";
import {
  getAuth,
  signInWithPopup,
  GoogleAuthProvider,
  signOut,
} from "https://www.gstatic.com/firebasejs/11.0.0/firebase-auth.js";

async function main() {
  const configEl = document.getElementById("firebase-config");
  let config = null;
  if (configEl && configEl.dataset.config) {
    try {
      config = JSON.parse(configEl.dataset.config);
    } catch (e) {
      console.error("Invalid firebase config json", e);
    }
  }
  if (!config) {
    try {
      const res = await fetch("/auth/config");
      config = await res.json();
    } catch (e) {
      console.error("Failed to load /auth/config", e);
    }
  }

  if (!config || !config.apiKey) {
    const errBox = document.getElementById("error-box");
    if (errBox) {
      errBox.textContent = "无法加载 Firebase 配置，请联系管理员。";
      errBox.style.display = "block";
    }
    return;
  }

  const app = initializeApp(config);
  const auth = getAuth(app);
  const provider = new GoogleAuthProvider();

  const loginBtn = document.getElementById("login-btn");
  const errBox = document.getElementById("error-box");
  const btnText = document.getElementById("login-btn-text");
  const btnSpinner = document.getElementById("login-btn-spinner");

  if (!loginBtn) return;

  loginBtn.addEventListener("click", async () => {
    loginBtn.disabled = true;
    if (errBox) {
      errBox.style.display = "none";
      errBox.textContent = "";
    }
    if (btnText) btnText.textContent = "正在登录...";
    if (btnSpinner) btnSpinner.style.display = "inline-block";

    try {
      const result = await signInWithPopup(auth, provider);
      const user = result.user;
      const idToken = await user.getIdToken();

      const sessionResp = await fetch("/auth/session", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ idToken }),
      });

      // Sign the user out of the Firebase client after the session is created
      // (server session is the source of truth)
      await signOut(auth);

      if (sessionResp.ok) {
        window.location.href = "/";
        return;
      }

      let errorMsg = "登录失败，请重试";
      if (sessionResp.status === 403) {
        errorMsg = "该 Google 账号未在管理员白名单中，无权访问";
      } else if (sessionResp.status === 401) {
        errorMsg = "身份验证失败或令牌已失效，请重新登录";
      } else if (sessionResp.status === 429) {
        errorMsg = "登录请求过于频繁，请稍后 1 分钟后再试";
      }
      if (errBox) {
        errBox.textContent = errorMsg;
        errBox.style.display = "block";
      }
    } catch (error) {
      await signOut(auth).catch(() => {});
      console.error("Sign-in error:", error);
      let errorMsg = "登录失败，请重试";
      if (error.code === "auth/popup-closed-by-user") {
        errorMsg = "登录弹窗已关闭，请重新点击登录";
      } else if (error.code === "auth/cancelled-popup-request") {
        errorMsg = "登录操作已取消";
      } else if (error.code === "auth/network-request-failed") {
        errorMsg = "网络连接失败，请检查网络后重试";
      } else if (error.message) {
        errorMsg = `登录错误: ${error.message}`;
      }
      if (errBox) {
        errBox.textContent = errorMsg;
        errBox.style.display = "block";
      }
    } finally {
      loginBtn.disabled = false;
      if (btnText) btnText.textContent = "使用 Google 账号登录";
      if (btnSpinner) btnSpinner.style.display = "none";
    }
  });
}

document.addEventListener("DOMContentLoaded", main);

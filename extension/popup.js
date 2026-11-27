const loginView = document.getElementById("login-view");
const loggedInView = document.getElementById("logged-in-view");
const errorEl = document.getElementById("error");

function showLoggedIn(username) {
  loginView.style.display = "none";
  loggedInView.style.display = "block";
  document.getElementById("logged-in-username").textContent = username || "";
}

function showLoginForm() {
  loginView.style.display = "block";
  loggedInView.style.display = "none";
}

async function refreshState() {
  const state = await chrome.runtime.sendMessage({ type: "atlasAuthState" });
  if (state?.loggedIn) {
    showLoggedIn(state.username);
  } else {
    showLoginForm();
  }
}

document.getElementById("login-btn").addEventListener("click", async () => {
  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value;
  errorEl.textContent = "";
  if (!username || !password) {
    errorEl.textContent = "יש למלא שם משתמש וסיסמה";
    return;
  }

  const result = await chrome.runtime.sendMessage({ type: "atlasLogin", username, password });
  if (result?.status === 200 && result.data.ok) {
    showLoggedIn(result.data.username);
  } else {
    errorEl.textContent = result?.data?.error || "שגיאה בהתחברות";
  }
});

document.getElementById("logout-btn").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ type: "atlasLogout" });
  showLoginForm();
});

refreshState();

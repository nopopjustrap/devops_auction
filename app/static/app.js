"use strict";

const authView = document.querySelector("#auth-view");
const appView = document.querySelector("#app-view");
const authForm = document.querySelector("#auth-form");
const authError = document.querySelector("#auth-error");
const authSubmit = document.querySelector("#auth-submit");
const resultTitle = document.querySelector("#result-title");
const resultOutput = document.querySelector("#result-output");
const toast = document.querySelector("#toast");

let authMode = "login";
let toastTimer;

async function api(path, options = {}) {
  const request = {
    method: options.method || "GET",
    credentials: "same-origin",
    headers: {},
  };
  if (options.body !== undefined) {
    request.headers["Content-Type"] = "application/json";
    request.body = JSON.stringify(options.body);
  }

  const response = await fetch(path, request);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : null;

  if (!response.ok) {
    const error = new Error(
      payload?.error?.message || `Ошибка HTTP ${response.status}`,
    );
    error.code = payload?.error?.code || "HTTP_ERROR";
    error.status = response.status;
    if (response.status === 401 && !path.endsWith("/auth/login")) {
      showAuth(false);
    }
    throw error;
  }
  return payload;
}

function setAuthMode(registrationOpen) {
  authMode = registrationOpen ? "register" : "login";
  document.querySelector("#auth-eyebrow").textContent = registrationOpen
    ? "Первый запуск"
    : "Вход оператора";
  document.querySelector("#auth-title").textContent = registrationOpen
    ? "Создайте оператора"
    : "Добро пожаловать";
  document.querySelector("#auth-description").textContent = registrationOpen
    ? "Это единственная открытая регистрация. Следующие пользователи через неё не создаются."
    : "Введите данные учётной записи, чтобы продолжить.";
  authSubmit.textContent = registrationOpen
    ? "Создать и войти"
    : "Войти";
}

function showAuth(registrationOpen) {
  setAuthMode(registrationOpen);
  authForm.reset();
  authError.hidden = true;
  authView.hidden = false;
  appView.hidden = true;
}

function showApp(user) {
  document.querySelector("#current-user").textContent =
    `${user.username} · ${user.role}`;
  authView.hidden = true;
  appView.hidden = false;
  checkHealth();
}

function cleanObject(value) {
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => item !== ""),
  );
}

function formValues(form) {
  return cleanObject(Object.fromEntries(new FormData(form).entries()));
}

function showResult(title, payload) {
  resultTitle.textContent = title;
  resultOutput.textContent = JSON.stringify(payload, null, 2);
  document
    .querySelector("#result-card")
    .scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function showToast(message, isError = false) {
  window.clearTimeout(toastTimer);
  toast.textContent = message;
  toast.classList.toggle("toast--error", isError);
  toast.hidden = false;
  toastTimer = window.setTimeout(() => {
    toast.hidden = true;
  }, 4200);
}

function fillInput(formId, name, value) {
  const input = document.querySelector(`#${formId} [name="${name}"]`);
  if (input) {
    input.value = value;
  }
}

function rememberCreated(entity, payload) {
  if (entity === "seller") {
    fillInput("lot-form", "seller_id", payload.id);
  }
  if (entity === "buyer") {
    fillInput("sale-form", "buyer_id", payload.id);
  }
  if (entity === "auction") {
    for (const formId of ["lot-form", "auction-status-form", "lookup-form"]) {
      fillInput(formId, "auction_id", payload.id);
    }
  }
  if (entity === "lot") {
    fillInput("sale-form", "lot_id", payload.id);
  }
}

async function submitOperation(button, title, operation) {
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Выполняется…";
  try {
    const payload = await operation();
    showResult(title, payload);
    showToast("Операция выполнена");
    return payload;
  } catch (error) {
    showResult("Ошибка", {
      code: error.code,
      message: error.message,
    });
    showToast(`${error.code}: ${error.message}`, true);
    return null;
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const credentials = formValues(authForm);
  authSubmit.disabled = true;
  authError.hidden = true;
  try {
    if (authMode === "register") {
      await api("/api/v1/auth/register", {
        method: "POST",
        body: credentials,
      });
    }
    const user = await api("/api/v1/auth/login", {
      method: "POST",
      body: credentials,
    });
    showApp(user);
  } catch (error) {
    authError.textContent = `${error.code}: ${error.message}`;
    authError.hidden = false;
  } finally {
    authSubmit.disabled = false;
  }
});

document.querySelector("#logout-button").addEventListener("click", async () => {
  try {
    await api("/api/v1/auth/logout", { method: "POST" });
  } finally {
    showAuth(false);
  }
});

document.querySelector("#seller-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = await submitOperation(
    event.submitter,
    "Продавец создан",
    () =>
      api("/api/v1/sellers", {
        method: "POST",
        body: formValues(form),
      }),
  );
  if (payload) {
    rememberCreated("seller", payload);
    form.reset();
  }
});

document.querySelector("#buyer-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = await submitOperation(
    event.submitter,
    "Покупатель создан",
    () =>
      api("/api/v1/buyers", {
        method: "POST",
        body: formValues(form),
      }),
  );
  if (payload) {
    rememberCreated("buyer", payload);
    form.reset();
  }
});

document.querySelector("#auction-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = formValues(form);
  values.starts_at = new Date(values.starts_at).toISOString();
  values.ends_at = new Date(values.ends_at).toISOString();
  const payload = await submitOperation(
    event.submitter,
    "Аукцион создан",
    () =>
      api("/api/v1/auctions", {
        method: "POST",
        body: values,
      }),
  );
  if (payload) {
    rememberCreated("auction", payload);
    form.reset();
  }
});

document.querySelector("#lot-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = formValues(form);
  const auctionId = values.auction_id;
  delete values.auction_id;
  values.seller_id = Number(values.seller_id);
  const payload = await submitOperation(
    event.submitter,
    "Лот добавлен",
    () =>
      api(`/api/v1/auctions/${auctionId}/lots`, {
        method: "POST",
        body: values,
      }),
  );
  if (payload) {
    rememberCreated("lot", payload);
  }
});

document
  .querySelector("#auction-status-form")
  .addEventListener("submit", async (event) => {
    event.preventDefault();
    const auctionId = formValues(event.currentTarget).auction_id;
    const action = event.submitter.value;
    await submitOperation(
      event.submitter,
      action === "open" ? "Аукцион открыт" : "Аукцион закрыт",
      () =>
        api(`/api/v1/auctions/${auctionId}/${action}`, {
          method: "POST",
        }),
    );
  });

document.querySelector("#sale-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = formValues(event.currentTarget);
  values.lot_id = Number(values.lot_id);
  values.buyer_id = Number(values.buyer_id);
  await submitOperation(
    event.submitter,
    "Продажа зарегистрирована",
    () =>
      api("/api/v1/sales", {
        method: "POST",
        body: values,
      }),
  );
});

document.querySelector("#lookup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const auctionId = formValues(event.currentTarget).auction_id;
  const action = event.submitter.value;
  const path =
    action === "lots"
      ? `/api/v1/auctions/${auctionId}/lots`
      : `/api/v1/reports/revenue?auction_id=${auctionId}`;
  await submitOperation(
    event.submitter,
    action === "lots" ? "Лоты аукциона" : "Отчёт по выручке",
    () => api(path),
  );
});

async function checkHealth() {
  const badge = document.querySelector("#health-badge");
  try {
    await api("/health");
    badge.textContent = "Сервис работает";
  } catch {
    badge.textContent = "Сервис недоступен";
  }
}

async function bootstrap() {
  try {
    const user = await api("/api/v1/auth/me");
    showApp(user);
  } catch {
    try {
      const status = await api("/api/v1/auth/status");
      showAuth(status.registration_open);
    } catch (error) {
      showAuth(false);
      authError.textContent = `Не удалось запустить интерфейс: ${error.message}`;
      authError.hidden = false;
    }
  }
}

bootstrap();

// Точка входа: три страницы одного собранного приложения.
//
//   /          рассказ о платформе и выбор пути (создать опрос или исследовать)
//   /app       рабочее место: данные и опросы
//   /s/<slug>  публичная форма опроса
//
// Разбор адреса здесь, а не в роутере-библиотеке: страниц всего три, и лишняя
// зависимость ради трёх веток не нужна.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { Home } from "./Home";
import { PublicForm } from "./PublicForm";
import "./styles.css";

const path = window.location.pathname.replace(/\/+$/, "") || "/";
const survey = /^\/s\/([^/]+)$/.exec(path);
const slug = survey ? decodeURIComponent(survey[1]) : "";

let page = <Home />;
if (slug) {
  page = <PublicForm slug={slug} />;
} else if (path === "/app") {
  page = <App />;
}

createRoot(document.getElementById("root")!).render(<StrictMode>{page}</StrictMode>);

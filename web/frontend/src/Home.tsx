// Главная страница сайта: что это за платформа и два пути.
//
// Человек сначала понимает, куда попал, и уже потом выбирает: создать опрос или
// исследовать данные. Оба пути ведут на /app - рабочее место; если он не вошёл,
// рабочее место само покажет вход.

import { useEffect, useState } from "react";
import { api, type User } from "./api";
import { applyTheme, initialTheme } from "./theme";

const STEPS = [
  {
    title: "Создайте опрос",
    text: "Название, вопросы, варианты. Черновик можно менять сколько угодно, пока не пришёл первый ответ.",
  },
  {
    title: "Отправьте ссылку",
    text: "Короткий адрес /s/… открывается без входа: участнику не нужен аккаунт. По умолчанию один браузер — один ответ.",
  },
  {
    title: "Исследуйте ответы",
    text: "Кнопка «Исследовать в Winnow» соберёт набор: вопрос — переменная, варианты — метки, множественные ответы — отметки 1/0.",
  },
];

export function Home() {
  const [theme, setTheme] = useState(() => initialTheme());
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // Если человек уже вошёл, в шапке полезнее «моё рабочее место», чем «войти».
  useEffect(() => {
    let alive = true;
    api
      .me()
      .then((found) => alive && setUser(found))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="landing">
      <header className="landing-head">
        <div className="brand">
          <span className="brand-mark">W</span>
          Winnow
        </div>
        <div className="landing-actions">
          <button
            type="button"
            className="ghost icon-button"
            title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
            aria-label={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? "☀" : "☾"}
          </button>
          <a className="button-link" href="/app">
            {user ? "Моё рабочее место" : "Войти"}
          </a>
        </div>
      </header>

      <section className="hero">
        <p className="eyebrow">Опросы и статистика в одном месте</p>
        <h1>Создайте опрос — и сразу исследуйте ответы</h1>
        <p className="lead">
          Winnow — платформа для сбора и анализа данных. Анкету заполняют по
          ссылке без регистрации, а её ответы превращаются в набор данных: дальше
          частоты, таблицы сопряжённости, сравнение групп, графики и отчёт
          простыми словами.
        </p>
      </section>

      <section className="home-choices">
        <a className="card choice-card" href="/app?section=surveys">
          <span className="choice-icon" aria-hidden="true">
            📝
          </span>
          <h2>Создать опрос</h2>
          <p>
            Конструктор анкеты: пять типов вопросов, обязательные вопросы,
            публикация и закрытие. Ссылку можно отправить любому человеку — вход
            участнику не нужен.
          </p>
          <span className="choice-go">Перейти к конструктору →</span>
        </a>

        <a className="card choice-card" href="/app?section=data">
          <span className="choice-icon" aria-hidden="true">
            📊
          </span>
          <h2>Исследовать данные</h2>
          <p>
            Загрузите файл CSV, Excel или SPSS — или возьмите ответы своего
            опроса. Программа посмотрит, что в данных есть, и предложит готовые
            исследования.
          </p>
          <span className="choice-go">Открыть Winnow →</span>
        </a>
      </section>

      <section className="steps">
        <h2>Как это работает</h2>
        <ol>
          {STEPS.map((step, index) => (
            <li key={step.title}>
              <span className="step-number">{index + 1}</span>
              <b>{step.title}</b>
              <span>{step.text}</span>
            </li>
          ))}
        </ol>
      </section>

      <footer className="landing-foot">
        Вход нужен только тому, кто создаёт опросы и работает с данными.
        Участнику опроса достаточно ссылки.
      </footer>
    </div>
  );
}

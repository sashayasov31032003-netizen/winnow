// Склонение числительных: «1 случай», «2 случая», «5 случаев».
export function plural(count: number, one: string, few: string, many: string): string {
  const tail = count % 100;
  if (tail >= 11 && tail <= 14) return `${count} ${many}`;
  const last = count % 10;
  if (last === 1) return `${count} ${one}`;
  if (last >= 2 && last <= 4) return `${count} ${few}`;
  return `${count} ${many}`;
}

//: Как называть статус опроса человеку. Сервер присылает draft/open/closed.
export function surveyStatusTitle(status: string): string {
  if (status === "open") return "Открыт";
  if (status === "closed") return "Закрыт";
  return "Черновик";
}

//: Время для списка ответов. Сервер присылает ISO с часовым поясом, браузер
//: показывает его в местном времени - человеку важно своё, а не UTC.
export function formatDateTime(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

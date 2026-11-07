// Значения полей анкеты и их проверка.
//
// Вынесено из PublicForm по двум причинам: предпросмотр в конструкторе
// проверяет ответы теми же правилами, что и настоящая форма, а файл с
// компонентами остаётся файлом с компонентами.

import type { AnswerInput, SurveyQuestion } from "./api";

export type QuestionValue = {
  option_ids: string[];
  value_number: string;
  value_text: string;
};

export type Answers = Record<number, QuestionValue>;

export function emptyValue(): QuestionValue {
  return { option_ids: [], value_number: "", value_text: "" };
}

/** Пустые значения для всех вопросов: их и держит форма. */
export function initialAnswers(questions: SurveyQuestion[]): Answers {
  const result: Answers = {};
  for (const question of questions) {
    if (question.id !== undefined) result[question.id] = emptyValue();
  }
  return result;
}

/** Ответа нет - это пропуск, а не пустая строка в базе. */
export function isEmpty(
  question: SurveyQuestion,
  value: QuestionValue | undefined,
): boolean {
  if (!value) return true;
  if (question.kind === "single" || question.kind === "multi") {
    return value.option_ids.length === 0;
  }
  if (question.kind === "text") return !value.value_text.trim();
  return !value.value_number.trim();
}

/** Какие обязательные вопросы остались без ответа. */
export function requiredErrors(
  questions: SurveyQuestion[],
  answers: Answers,
): Record<number, string> {
  const errors: Record<number, string> = {};
  for (const question of questions) {
    if (!question.required || question.id === undefined) continue;
    if (isEmpty(question, answers[question.id])) {
      errors[question.id] = "Ответьте на этот вопрос: он обязательный";
    }
  }
  return errors;
}

/** Ответы в том виде, в каком их принимает сервер. */
export function toAnswerInputs(
  questions: SurveyQuestion[],
  answers: Answers,
): AnswerInput[] {
  const result: AnswerInput[] = [];
  for (const question of questions) {
    if (question.id === undefined) continue;
    const value = answers[question.id];
    if (isEmpty(question, value)) continue;
    if (question.kind === "single" || question.kind === "multi") {
      result.push({ question_id: question.id, option_ids: value.option_ids });
    } else if (question.kind === "text") {
      result.push({ question_id: question.id, value_text: value.value_text.trim() });
    } else {
      result.push({
        question_id: question.id,
        value_number: Number(value.value_number.trim().replace(",", ".")),
      });
    }
  }
  return result;
}

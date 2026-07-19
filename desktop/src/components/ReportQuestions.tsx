const QUESTIONS = [
  { id: "happened", label: "What happened?", answer: "An approved move to Northlight Studio has not reached crew-facing documents." },
  { id: "evidence", label: "What evidence supports it?", answer: "Investor approval and Budget v4 support Northlight; calendar and call sheet still show Harbor House." },
  { id: "next", label: "What should happen next?", answer: "A production lead must update the calendar and call sheet before tomorrow’s briefing." },
] as const;

export function ReportQuestions() {
  return (
    <section className="report-questions" aria-label="Report reconstruction questions">
      {QUESTIONS.map((item) => (
        <article className="report-question" key={item.id}>
          <h3>{item.label}</h3>
          <p>{item.answer}</p>
        </article>
      ))}
    </section>
  );
}

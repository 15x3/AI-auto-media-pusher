export function Card({ title, note, active, children }: {
  title: string; note?: string; active?: boolean; children: React.ReactNode;
}) {
  return (
    <section className={`card${active ? " active" : ""}`}>
      <header className="card-title"><span>{title}</span>{note && <small>{note}</small>}</header>
      <div className="card-body">{children}</div>
    </section>
  );
}

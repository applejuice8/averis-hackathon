export default function Loading() {
  return <div aria-busy="true" aria-label="Loading workspace"><p className="eyebrow">Loading workspace</p><div className="cards">{[1,2,3,4].map(n => <div className="skeleton" key={n} />)}</div><div className="skeleton" style={{height:300}} /></div>;
}

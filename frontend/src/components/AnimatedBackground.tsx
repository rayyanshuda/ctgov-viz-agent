// A decorative layer behind the whole app: soft colour blobs drifting slowly, plus a fine
// grain. All the styling is in index.css (.blob, .grain). It is hidden from screen readers
// and ignores the mouse, so it never gets in the way.

export function AnimatedBackground() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div className="blob blob-pink" />
      <div className="blob blob-purple" />
      <div className="blob blob-blue" />
      <div className="blob blob-peach" />
      <div className="grain" />
    </div>
  );
}

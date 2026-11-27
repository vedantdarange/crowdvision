export function ConnectionDot({
  state,
}: {
  state: 'connected' | 'reconnecting' | 'offline';
}) {
  const labels = {
    connected: 'Connected',
    reconnecting: 'Reconnecting',
    offline: 'Offline',
  };
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm">
      <span
        aria-hidden="true"
        className={`size-2 rounded-full ${state === 'connected' ? 'bg-safe' : state === 'reconnecting' ? 'bg-warning' : 'bg-no-data'}`}
      />
      {labels[state]}
    </span>
  );
}

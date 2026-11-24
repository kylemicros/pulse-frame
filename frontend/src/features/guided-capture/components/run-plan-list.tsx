export function RunPlanList() {
  return (
    <ol className="list-decimal pl-5.5">
      <li className="mb-1.5">
        <strong>Warm-up, 60 s.</strong> Stay in frame. No need to watch the screen.
      </li>
      <li className="mb-1.5">
        <strong>Counted, 90 s.</strong> Hold still. We chime and say so when it starts and ends.
      </li>
      <li className="mb-1.5">
        <strong>Result.</strong> Your average heart rate over the last counted minute.
      </li>
    </ol>
  )
}

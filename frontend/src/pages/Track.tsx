import TrackRecord from "../components/TrackRecord";

export default function Track() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Track record</h1>
        <p className="text-sm text-mute">Every signal since launch and its real outcome, plus how the AI scored on past data it never saw. This page is public, so visitors can check it before they join.</p>
      </div>
      <TrackRecord />
    </div>
  );
}

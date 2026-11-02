import TrackRecord from "../components/TrackRecord";

export default function Track() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="page-title">Track record</h1>
        <p className="text-sm text-mute">Every signal and its real outcome. Members only.</p>
      </div>
      <TrackRecord />
    </div>
  );
}

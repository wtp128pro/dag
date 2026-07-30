I42 green control: every inputs_reviewed element is an evidence object with a run-relative path that
exists and a sha256 that matches the file's current bytes. A green control pins nothing on its own;
it exists to catch OVER-firing.

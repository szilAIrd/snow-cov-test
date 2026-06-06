import { useRef, useState } from "react";

interface Props {
  onFile: (file: File) => void;
  loading: boolean;
}

export function GPXUpload({ onFile, loading }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);

  const handleFile = (file: File) => {
    setFilename(file.name);
    onFile(file);
  };

  const onChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDrag(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  return (
    <div
      className={`upload-card${drag ? " dragover" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={onDrop}
      onClick={() => !loading && inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".gpx,application/gpx+xml,application/xml,text/xml"
        onChange={onChange}
        disabled={loading}
      />
      <label>
        <span className="upload-icon">🏔</span>
        {filename ? (
          <span className="filename">{filename}</span>
        ) : (
          <>
            <p>Drop a GPX file here</p>
            <p className="hint">or click to browse</p>
          </>
        )}
      </label>
    </div>
  );
}

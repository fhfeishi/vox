// web/src/components/Subtitle.tsx
export function Subtitle({ text, isSpeaking }: { text: string; isSpeaking: boolean }) {
    return (
      <div style={{ marginTop: '50px', height: '100px', fontSize: '24px', color: '#2c3e50', width: '80%', textAlign: 'center' }}>
        {isSpeaking && <div style={{ fontSize: '14px', color: '#e67e22', marginBottom: '10px' }}>正在聆听...</div>}
        {text || "等待说话..."}
      </div>
    );
  }
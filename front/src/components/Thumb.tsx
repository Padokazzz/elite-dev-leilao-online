import { useState } from "react";

type ThumbProps = {
  /** URL do proxy de imagem; null/undefined renderiza o placeholder. */
  src: string | null | undefined;
  alt: string;
  /** Classe de tamanho (ex.: auction-thumb, mine-thumb). */
  className?: string;
};

/**
 * Miniatura com degradação elegante: se a imagem faltar ou falhar,
 * mostra a inicial do título no mesmo quadro (sem layout quebrado).
 */
export default function Thumb({ src, alt, className }: ThumbProps) {
  const [failed, setFailed] = useState(false);
  const classes = ["thumb", className ?? ""].filter(Boolean).join(" ");

  if (src && !failed) {
    return (
      <img
        className={classes}
        src={src}
        alt={alt}
        loading="lazy"
        onError={() => setFailed(true)}
      />
    );
  }

  return (
    <div className={`${classes} placeholder`} aria-hidden="true">
      {alt.trim().charAt(0).toUpperCase() || "?"}
    </div>
  );
}

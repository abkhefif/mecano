interface ImageModalProps {
  url: string;
  alt: string;
  onClose: () => void;
}

export function ImageModal({ url, alt, onClose }: ImageModalProps) {
  return (
    <div
      className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <button
        onClick={onClose}
        className="absolute top-4 right-4 text-white text-3xl font-bold hover:text-gray-300 z-10"
      >
        &times;
      </button>
      <img
        src={url}
        alt={alt}
        className="max-w-full max-h-full object-contain rounded-lg"
        onClick={(e) => e.stopPropagation()}
      />
    </div>
  );
}

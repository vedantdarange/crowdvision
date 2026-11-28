export const MAX_REPORT_IMAGE_BYTES = 5 * 1024 * 1024;
export const DEFAULT_MAX_SIDE_PX = 1280;
export const DEFAULT_JPEG_QUALITY = 0.8;

export interface DownscaledImageResult {
  blob: Blob;
  width: number;
  height: number;
}

export interface LoadedImageLike {
  width: number;
  height: number;
}

export interface DownscaleDeps {
  loadImage?: (file: File) => Promise<{
    image: LoadedImageLike & CanvasImageSource;
    release: () => void;
  }>;
  createCanvas?: (
    width: number,
    height: number,
  ) => {
    draw: (image: CanvasImageSource, width: number, height: number) => void;
    toJpegBlob: (quality: number) => Promise<Blob | null>;
  };
}

/** Scales width/height proportionally so the longest side never exceeds maxSide. */
export function fitDimensions(
  width: number,
  height: number,
  maxSide = DEFAULT_MAX_SIDE_PX,
): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (longest <= 0 || width <= 0 || height <= 0) {
    throw new Error('Could not read image dimensions.');
  }
  if (longest <= maxSide) {
    return { width: Math.round(width), height: Math.round(height) };
  }
  const scale = maxSide / longest;
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

async function defaultLoadImage(file: File): Promise<{
  image: HTMLImageElement;
  release: () => void;
}> {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () =>
        reject(new Error('Could not decode the selected image file.'));
      el.src = url;
    });
    return {
      image: img,
      release: () => URL.revokeObjectURL(url),
    };
  } catch (err) {
    URL.revokeObjectURL(url);
    throw err;
  }
}

function defaultCreateCanvas(width: number, height: number) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    throw new Error('Image processing canvas is unavailable.');
  }
  return {
    draw(image: CanvasImageSource, w: number, h: number) {
      ctx.drawImage(image, 0, 0, w, h);
    },
    toJpegBlob(quality: number) {
      return new Promise<Blob | null>((resolve) => {
        canvas.toBlob((blob) => resolve(blob), 'image/jpeg', quality);
      });
    },
  };
}

/** Re-encodes and downscales a selected photo to <= 1280 px JPEG at quality 0.8 in RAM. */
export async function downscaleCrowdImage(
  file: File,
  {
    maxSide = DEFAULT_MAX_SIDE_PX,
    quality = DEFAULT_JPEG_QUALITY,
    deps,
  }: {
    maxSide?: number;
    quality?: number;
    deps?: DownscaleDeps;
  } = {},
): Promise<DownscaledImageResult> {
  if (!file.type.startsWith('image/')) {
    throw new Error('Please choose an image file (JPEG or PNG).');
  }

  const load = deps?.loadImage ?? defaultLoadImage;
  const makeCanvas = deps?.createCanvas ?? defaultCreateCanvas;

  const { image, release } = await load(file);
  try {
    const naturalWidth =
      'naturalWidth' in image
        ? (image as HTMLImageElement).naturalWidth || image.width
        : image.width;
    const naturalHeight =
      'naturalHeight' in image
        ? (image as HTMLImageElement).naturalHeight || image.height
        : image.height;
    const { width, height } = fitDimensions(
      naturalWidth,
      naturalHeight,
      maxSide,
    );
    const surface = makeCanvas(width, height);
    surface.draw(image, width, height);
    const blob = await surface.toJpegBlob(quality);
    if (!blob) {
      throw new Error('Could not encode photo as JPEG.');
    }
    if (blob.size > MAX_REPORT_IMAGE_BYTES) {
      throw new Error(
        'Processed photo exceeds the 5 MB upload limit. Please try a closer or lower-resolution photo.',
      );
    }
    return { blob, width, height };
  } finally {
    release();
  }
}

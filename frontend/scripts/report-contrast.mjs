import { readFileSync } from 'node:fs';
const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8');
function luminance(hex) {
  const rgb = hex
    .match(/[a-f\d]{2}/gi)
    .map((c) => parseInt(c, 16) / 255)
    .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
}
for (const mode of ['light', 'dark'])
  for (const level of ['safe', 'warning', 'critical', 'no-data']) {
    const block =
      mode === 'light'
        ? css.split(':root {').at(-1).split('.dark')[0]
        : css.split('.dark {').at(-1);
    const fg = block.match(new RegExp(`--level-${level}: (#[a-f0-9]+)`))[1],
      bg = block.match(new RegExp(`--level-${level}-bg: (#[a-f0-9]+)`))[1];
    const [low, high] = [luminance(fg), luminance(bg)].sort((a, b) => a - b),
      ratio = (high + 0.05) / (low + 0.05);
    process.stdout.write(
      `${mode} ${level}: ${fg} on ${bg} = ${ratio.toFixed(2)}:1\n`,
    );
    if (ratio < 4.5) process.exitCode = 1;
  }

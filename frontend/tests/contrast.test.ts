// @vitest-environment node
import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';
function luminance(hex: string) {
  const rgb = hex
    .match(/[a-f\d]{2}/gi)!
    .map((c) => parseInt(c, 16) / 255)
    .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return rgb[0]! * 0.2126 + rgb[1]! * 0.7152 + rgb[2]! * 0.0722;
}
const css = readFileSync('src/index.css', 'utf8');
for (const mode of ['light', 'dark'])
  for (const level of ['safe', 'warning', 'critical', 'no-data'])
    it(`${mode} ${level} text contrast is at least 4.5:1`, () => {
      const block =
        mode === 'light'
          ? css.split(':root {').at(-1)!.split('.dark')[0]!
          : css.split('.dark {').at(-1)!;
      const foreground = block.match(
        new RegExp(`--level-${level}: (#[a-f0-9]+)`),
      )![1]!;
      const background = block.match(
        new RegExp(`--level-${level}-bg: (#[a-f0-9]+)`),
      )![1]!;
      const values = [luminance(foreground), luminance(background)].sort(
          (a, b) => a - b,
        ),
        ratio = (values[1]! + 0.05) / (values[0]! + 0.05);
      expect(
        ratio,
        `${foreground} on ${background}: ${ratio.toFixed(2)}:1`,
      ).toBeGreaterThanOrEqual(4.5);
    });

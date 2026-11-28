import { zodResolver } from '@hookform/resolvers/zod';
import {
  bounds,
  numericSchema,
  thresholdsValid,
  thresholdIssue,
  wholeNumber,
} from './settingsSchema';
import { useForm } from 'react-hook-form';
import type { Settings } from '@contract/types';
import { Button } from '@/components/ui/button';
import { ManagementPage, WriteError } from './ManagementLayout';
import { useSettings, useSaveSettings } from './managementApi';
import { HelpEditor } from './HelpEditor';

type Numeric = Omit<Settings, 'help_info'>;
type Spec = [keyof Numeric, string, string, string];
const settingsSchema = numericSchema.refine(thresholdsValid, thresholdIssue);
const groups: Record<string, Spec[]> = {
  Detection: [
    [
      'detect_conf',
      'Detection confidence',
      'ratio',
      'Count a person only when detector confidence reaches this value.',
    ],
    [
      'smoothing_window',
      'Smoothing window',
      'frames',
      'Take the median count over this many recent frames.',
    ],
    [
      'target_fps',
      'Capture rate',
      'frames/s',
      'Limit how many frames each source sends per second.',
    ],
    [
      'frame_width',
      'Frame width',
      'px',
      'Resize each captured frame to this width before sending it.',
    ],
    [
      'jpeg_quality',
      'JPEG quality',
      'ratio',
      'Higher quality preserves more detail and sends larger images.',
    ],
    [
      'stale_after_s',
      'Feed timeout',
      's',
      'Mark a source offline after this long without a frame.',
    ],
  ],
  Alerting: [
    [
      'debounce_s',
      'Rise delay',
      's',
      'Wait this long above a threshold before raising the level.',
    ],
    [
      'clear_s',
      'Clear delay',
      's',
      'Wait this long below the clearing threshold before lowering the level.',
    ],
    [
      'hysteresis_ratio',
      'Hysteresis',
      'ratio',
      'The level can step down once the reading falls below this fraction of its threshold.',
    ],
    [
      'cooldown_s',
      'Warning cooldown',
      's',
      'Wait this long between warning notifications for one zone.',
    ],
    [
      'escalation_s',
      'Critical reminder interval',
      's',
      'Repeat notifications at this interval while a critical alert awaits acknowledgement.',
    ],
    [
      'reraise_after_s',
      'Re-raise delay',
      's',
      'After resolution, a zone still over its limit raises a new alert after this delay (default 60 s).',
    ],
  ],
  Defaults: [
    [
      'default_warning_density',
      'Default warning density',
      'people/m²',
      'New zones enter warning at this density unless their threshold is customized.',
    ],
    [
      'default_critical_density',
      'Default critical density',
      'people/m²',
      'New zones enter critical at this density unless their threshold is customized.',
    ],
  ],
};
export function numericDiff(
  original: Numeric,
  values: Numeric,
): Partial<Numeric> {
  const patch: Partial<Numeric> = {};
  for (const fields of Object.values(groups))
    for (const [key] of fields)
      if (values[key] !== original[key]) patch[key] = values[key];
  return patch;
}
function NumericEditor({ settings }: { settings: Settings }) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { defaultValues, isDirty, errors },
  } = useForm<Numeric>({
    defaultValues: settings,
    resolver: zodResolver(settingsSchema),
  });
  const save = useSaveSettings();
  return (
    <form
      className="space-y-4"
      onSubmit={handleSubmit((values) => {
        const patch = numericDiff(defaultValues as Numeric, values);
        if (Object.keys(patch).length)
          save.mutate(patch, { onSuccess: (data) => reset(data) });
      })}
    >
      <fieldset disabled={save.isPending} className="space-y-4">
        {Object.entries(groups).map(([group, fields]) => (
          <section key={group} className="glass">
            <h2>{group}</h2>
            <div className="police-filters">
              {fields.map(([key, label, unit, hint]) => {
                const [min, max] = bounds[key];
                return (
                  <div key={key}>
                    <label>
                      {label} ({unit})
                      <input
                        aria-describedby={key + '-hint'}
                        type="number"
                        required
                        min={min}
                        max={max}
                        step={wholeNumber(key) ? 1 : 'any'}
                        {...register(key, { valueAsNumber: true })}
                      />
                    </label>
                    <small id={key + '-hint'}>
                      {min}–{max} {unit}. {hint}
                    </small>
                    {errors[key] && <p role="alert">{errors[key]?.message}</p>}
                  </div>
                );
              })}
            </div>
          </section>
        ))}
        <Button disabled={!isDirty}>Save settings</Button>
      </fieldset>
      <WriteError error={save.error} />
    </form>
  );
}
function Editors() {
  const { data } = useSettings();
  return (
    <>
      <NumericEditor settings={data} />
      <HelpEditor help={data.help_info} />
    </>
  );
}
export function Component() {
  return (
    <ManagementPage title="Settings">
      <Editors />
    </ManagementPage>
  );
}

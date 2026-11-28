import { zodResolver } from '@hookform/resolvers/zod';
import { helpSchema } from './settingsSchema';
import { useFieldArray, useForm, type UseFormReturn } from 'react-hook-form';
import type { HelpInfo } from '@contract/types';
import { Button } from '@/components/ui/button';
import { useSaveSettings } from './managementApi';
import { WriteError } from './ManagementLayout';
type LocationGroup = 'medical_points' | 'exits';
function Places({
  form,
  name,
  title,
}: {
  form: UseFormReturn<HelpInfo>;
  name: LocationGroup;
  title: string;
}) {
  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name,
  });
  return (
    <section>
      <h3>{title}</h3>
      {!fields.length && <p>No {title.toLowerCase()} listed.</p>}
      {fields.map((field, i) => (
        <fieldset className="police-filters" key={field.id}>
          <legend>
            {title} · {i + 1}
          </legend>
          <label>
            Name
            <input
              required
              maxLength={120}
              {...form.register(`${name}.${i}.name`)}
            />
          </label>
          {(['lat', 'lng'] as const).map((axis) => (
            <label key={axis}>
              {axis === 'lat' ? 'Latitude' : 'Longitude'}
              <input
                type="number"
                step="any"
                min={axis === 'lat' ? -90 : -180}
                max={axis === 'lat' ? 90 : 180}
                {...form.register(`${name}.${i}.${axis}`, {
                  setValueAs: (v) => (v === '' || v == null ? null : Number(v)),
                })}
              />
            </label>
          ))}
          <label>
            Note
            <input
              maxLength={500}
              {...form.register(`${name}.${i}.note`, {
                setValueAs: (v) => v || null,
              })}
            />
          </label>
          <Button variant="outline" type="button" onClick={() => remove(i)}>
            Remove row {i + 1}
          </Button>
        </fieldset>
      ))}
      <Button
        type="button"
        variant="outline"
        onClick={() => append({ name: '', lat: null, lng: null, note: null })}
      >
        Add {name === 'exits' ? 'exit' : 'medical point'}
      </Button>
    </section>
  );
}
export function HelpEditor({ help }: { help: HelpInfo }) {
  const form = useForm<HelpInfo>({
    defaultValues: help,
    resolver: zodResolver(helpSchema),
  });
  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: 'emergency_numbers',
  });
  const save = useSaveSettings();
  return (
    <form
      className="glass space-y-3"
      onSubmit={form.handleSubmit((help_info) =>
        save.mutate(
          { help_info },
          { onSuccess: (data) => form.reset(data.help_info) },
        ),
      )}
    >
      <h2>Public help information</h2>
      <fieldset className="space-y-4" disabled={save.isPending}>
        <section>
          <h3>Emergency numbers</h3>
          {!fields.length && <p>No emergency numbers listed.</p>}
          {fields.map((field, i) => (
            <fieldset className="police-filters" key={field.id}>
              <legend>Emergency number {i + 1}</legend>
              <label>
                Label
                <input
                  required
                  maxLength={100}
                  {...form.register(`emergency_numbers.${i}.label`)}
                />
              </label>
              <label>
                Phone number
                <input
                  required
                  type="tel"
                  maxLength={50}
                  {...form.register(`emergency_numbers.${i}.number`)}
                />
              </label>
              <Button type="button" variant="outline" onClick={() => remove(i)}>
                Remove number {i + 1}
              </Button>
            </fieldset>
          ))}
          <Button
            variant="outline"
            type="button"
            onClick={() => append({ label: '', number: '' })}
          >
            Add emergency number
          </Button>
        </section>
        <Places form={form} name="medical_points" title="Medical points" />
        <Places form={form} name="exits" title="Exits" />
        <Button disabled={!form.formState.isDirty}>
          Save help information
        </Button>
      </fieldset>
      <WriteError error={save.error} />
    </form>
  );
}

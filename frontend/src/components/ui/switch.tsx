import * as React from 'react';
import { cn } from '@/lib/utils';
import { Switch as SwitchPrimitive } from 'radix-ui';

function Switch({
  className,
  size = 'default',
  ...props
}: React.ComponentProps<typeof SwitchPrimitive.Root> & {
  size?: 'sm' | 'default';
}) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      data-size={size}
      className={cn(
        'peer group/switch relative inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-md border border-transparent transition-all outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 data-disabled:cursor-not-allowed data-disabled:opacity-50',
        className,
      )}
      {...props}
    >
      <span
        aria-hidden
        className="flex items-center rounded-full border border-transparent bg-input p-0.5 transition-colors group-data-[size=default]/switch:h-6 group-data-[size=default]/switch:w-11 group-data-[size=sm]/switch:h-5 group-data-[size=sm]/switch:w-9 group-data-checked/switch:bg-primary dark:bg-input/80"
      >
        <SwitchPrimitive.Thumb
          data-slot="switch-thumb"
          className="pointer-events-none block rounded-full bg-background ring-0 transition-transform group-data-[size=default]/switch:size-5 group-data-[size=sm]/switch:size-4 group-data-[size=default]/switch:data-checked:translate-x-5 group-data-[size=sm]/switch:data-checked:translate-x-4 dark:data-checked:bg-primary-foreground group-data-unchecked:translate-x-0 dark:data-unchecked:bg-foreground"
        />
      </span>
    </SwitchPrimitive.Root>
  );
}

export { Switch };

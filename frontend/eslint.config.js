import tseslint from 'typescript-eslint';
import hooks from 'eslint-plugin-react-hooks';

export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**', 'scripts/.fixtures.generated.ts'] },
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    plugins: { 'react-hooks': hooks },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'error',
      'no-console': ['error', { allow: ['warn', 'error'] }],
      'no-restricted-syntax': [
        'error',
        {
          selector: "NewExpression[callee.name='Notification']",
          message:
            'Never call new Notification() in page code; use ServiceWorkerRegistration.showNotification() instead.',
        },
        {
          selector: "NewExpression[callee.property.name='Notification']",
          message:
            'Never call new window.Notification() or globalThis.Notification(); use ServiceWorkerRegistration.showNotification() instead.',
        },
      ],
    },
  },
);

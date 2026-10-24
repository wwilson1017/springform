import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  // types.gen.ts is openapi-typescript output; CI regenerates it and fails on any diff.
  { ignores: ['dist', 'src/core/api/types.gen.ts'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
    },
  },
  {
    // Modules whose contract is a non-component export: an app's default `{ slug, App }`, a core
    // area's route list, and a context's provider beside its hook. Fast refresh reloads them whole.
    files: ['src/apps/*/index.tsx', 'src/core/*/routes.tsx', 'src/core/*/*Context.tsx'],
    rules: { 'react-refresh/only-export-components': 'off' },
  },
)

import js from '@eslint/js'
import globals from 'globals'
import pluginVue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'

export default [
  {
    ignores: ['dist/**', 'node_modules/**', 'coverage/**'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/essential'],
  {
    files: ['**/*.{ts,tsx,vue}'],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.es2024,
      },
    },
    rules: {
      'no-empty': ['error', { allowEmptyCatch: false }],
      'no-debugger': 'error',
      'no-console': 'error',
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
      '@typescript-eslint/no-explicit-any': 'warn',
      'vue/multi-word-component-names': 'off',
      'vue/no-v-html': 'warn',
    },
  },
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
        extraFileExtensions: ['.vue'],
      },
    },
  },
  {
    files: ['src/utils/logger.ts', 'src/**/__tests__/**/*.ts'],
    rules: {
      'no-console': 'off',
    },
  },
  {
    files: ['src/**/__tests__/**/*.ts'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
]

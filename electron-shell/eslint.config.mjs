export default [
  {
    files: ['electron-shell/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'commonjs',
      globals: {
        require: 'readonly',
        module: 'readonly',
        exports: 'readonly',
        __dirname: 'readonly',
        __filename: 'readonly',
        process: 'readonly',
        Buffer: 'readonly',
        console: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        setInterval: 'readonly',
        clearInterval: 'readonly',
        URL: 'readonly',
        Set: 'readonly',
        Map: 'readonly',
        Promise: 'readonly',
        Intl: 'readonly',
      },
    },
    rules: {
      'no-empty': ['error', { allowEmptyCatch: false }],
      'no-undef': 'error',
      'no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
      'no-debugger': 'error',
      'no-redeclare': 'error',
      'no-unreachable': 'error',
    },
  },
]

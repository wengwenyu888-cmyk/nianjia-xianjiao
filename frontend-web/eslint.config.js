// ESLint 9 flat config：Vue3 + TS 基础规则
import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'

export default [
  {
    // 构建产物、依赖与自动生成的类型声明不参与 lint
    ignores: ['dist/**', 'node_modules/**', 'src/types/**']
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  {
    files: ['**/*.{ts,vue}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      // .vue 里的 <script setup lang="ts"> 需要显式指定 TS 解析器，
      // 否则 vue-eslint-parser 会用 espree 解析，报 "Parsing error: Unexpected token"
      parserOptions: {
        parser: tseslint.parser
      }
    },
    rules: {
      'vue/multi-word-component-names': 'off',
      '@typescript-eslint/no-explicit-any': 'warn'
    }
  }
]

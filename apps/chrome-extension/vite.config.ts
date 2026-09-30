import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
const here = fileURLToPath(new URL('.', import.meta.url));
export default defineConfig({ plugins: [react()], build: { outDir: 'dist', rollupOptions: { input: { popup: resolve(here, 'index.html'), background: resolve(here, 'src/background.ts'), content: resolve(here, 'src/content.ts') }, output: { entryFileNames: chunk => chunk.name === 'background' || chunk.name === 'content' ? `${chunk.name}.js` : 'assets/[name].js' } } } });

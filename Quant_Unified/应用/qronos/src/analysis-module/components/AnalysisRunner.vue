<template>
  <div class="analysis-runner w-full h-full flex flex-col gap-6">
    <!-- Header Section -->
    <div class="flex items-center justify-between p-6 rounded-2xl bg-white/5 backdrop-blur-xl border border-white/10 shadow-xl">
      <div>
        <h2 class="text-2xl font-bold bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-transparent">
          {{ title }}
        </h2>
        <p class="text-gray-400 mt-2 text-sm">{{ description }}</p>
      </div>
      
      <button 
        @click="runAnalysis" 
        :disabled="isRunning"
        class="px-6 py-3 rounded-xl font-medium transition-all duration-300 transform hover:scale-105 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        :class="isRunning ? 'bg-gray-700 text-gray-400' : 'bg-gradient-to-r from-blue-500 to-purple-600 text-white shadow-lg shadow-blue-500/30'"
      >
        <i class="pi pi-play" :class="{'animate-spin': isRunning}"></i>
        {{ isRunning ? '运行中...' : '开始分析' }}
      </button>
    </div>

    <!-- Content Area -->
    <div class="flex-1 flex gap-6 min-h-0">
      <!-- Left: Logs (Terminal Style) -->
      <div class="w-1/3 flex flex-col rounded-2xl bg-[#0f111a] border border-white/5 shadow-inner overflow-hidden">
        <div class="px-4 py-3 border-b border-white/5 bg-white/5 flex items-center justify-between">
          <span class="text-xs font-mono text-gray-400">TERMINAL OUTPUT</span>
          <div class="flex gap-2">
            <div class="w-2.5 h-2.5 rounded-full bg-red-500/20"></div>
            <div class="w-2.5 h-2.5 rounded-full bg-yellow-500/20"></div>
            <div class="w-2.5 h-2.5 rounded-full bg-green-500/20"></div>
          </div>
        </div>
        <div class="flex-1 overflow-y-auto p-4 font-mono text-xs space-y-1 custom-scrollbar" ref="logContainer">
          <div v-if="logs.length === 0" class="text-gray-600 italic">等待执行...</div>
          <div v-for="(log, index) in logs" :key="index" class="text-gray-300 break-all hover:bg-white/5 px-1 rounded transition-colors">
            <span class="text-blue-500 mr-2">➜</span>{{ log }}
          </div>
        </div>
      </div>

      <!-- Right: Preview / Report -->
      <div class="w-2/3 flex flex-col rounded-2xl bg-white/5 backdrop-blur-md border border-white/10 overflow-hidden relative group">
        <div v-if="!reportUrl && !isRunning" class="absolute inset-0 flex flex-col items-center justify-center text-gray-500">
          <i class="pi pi-chart-bar text-6xl mb-4 opacity-20"></i>
          <p>运行分析以生成报告</p>
        </div>
        
        <div v-if="isRunning && !reportUrl" class="absolute inset-0 flex flex-col items-center justify-center z-10 bg-black/20 backdrop-blur-sm">
           <div class="w-16 h-16 border-4 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
           <p class="mt-4 text-blue-400 font-medium tracking-wider animate-pulse">正在生成分析报告...</p>
        </div>

        <iframe 
          v-if="reportUrl" 
          :src="reportUrl" 
          class="w-full h-full border-0 bg-white"
        ></iframe>
        
        <!-- Action Bar for Report -->
        <div v-if="reportUrl" class="absolute top-4 right-4 flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity duration-300">
            <a :href="reportUrl" target="_blank" class="p-2 bg-black/50 backdrop-blur text-white rounded-lg hover:bg-blue-600 transition-colors" title="在新窗口打开">
                <i class="pi pi-external-link"></i>
            </a>
            <button @click="$emit('refresh')" class="p-2 bg-black/50 backdrop-blur text-white rounded-lg hover:bg-green-600 transition-colors" title="刷新">
                <i class="pi pi-refresh"></i>
            </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue';

const props = defineProps<{
  title: string;
  description: string;
  isRunning: boolean;
  logs: string[];
  reportUrl?: string;
}>();

const emit = defineEmits<{
  (e: 'run'): void;
  (e: 'refresh'): void;
}>();

const logContainer = ref<HTMLElement | null>(null);

const runAnalysis = () => {
  emit('run');
};

watch(() => props.logs.length, () => {
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight;
    }
  });
});
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.2);
}
</style>

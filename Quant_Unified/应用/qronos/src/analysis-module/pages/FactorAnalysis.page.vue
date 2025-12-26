<template>
  <div class="h-full flex flex-col p-6">
    <div class="flex-1 relative h-full">
      <AnalysisRunner
        title="因子分析"
        description="分析因子的分箱收益和分组净值，评估因子有效性。"
        :is-running="isRunning"
        :logs="logs"
        :report-url="currentReportUrl"
        @run="runAnalysis"
        @refresh="refreshReport"
      />
      
      <!-- Report Selector -->
      <div v-if="reports.length > 0" class="absolute top-24 left-1/2 transform -translate-x-1/2 z-20">
         <div class="flex items-center gap-2 bg-black/40 backdrop-blur-md p-2 rounded-xl border border-white/10">
            <span class="text-xs text-gray-400">选择报告:</span>
            <select v-model="selectedReport" class="bg-transparent text-white text-sm outline-none cursor-pointer">
                <option v-for="r in reports" :key="r" :value="r" class="bg-gray-800">{{ r }}</option>
            </select>
         </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import AnalysisRunner from '../components/AnalysisRunner.vue';
import http from '@/common-module/services/http.provider';

const isRunning = ref(false);
const logs = ref<string[]>([]);
const reports = ref<string[]>([]);
const selectedReport = ref<string>('');

const currentReportUrl = computed(() => {
  if (!selectedReport.value) return undefined;
  const base = window.location.origin;
  return `${base}/qronos/analysis/factor/report/${selectedReport.value}/html`;
});

const runAnalysis = async () => {
  isRunning.value = true;
  logs.value = [];
  try {
    const res: any = await http.post('/qronos/analysis/factor/run', false, {}, { baseUrl: '', timeoutSeconds: 600 });
    if (res.code === 200) {
        logs.value = res.data.logs;
        await loadReports();
    } else {
        logs.value.push(`Error: ${res.msg}`);
    }
  } catch (e: any) {
    logs.value.push(`Error: ${e.message || e}`);
  } finally {
    isRunning.value = false;
  }
};

const loadReports = async () => {
    try {
        const res: any = await http.get('/qronos/analysis/factor/reports', false, {}, { baseUrl: '' });
        if (res.code === 200) {
            reports.value = res.data;
            if (reports.value.length > 0 && !selectedReport.value) {
                selectedReport.value = reports.value[0];
            }
        }
    } catch (e) {
        console.error(e);
    }
};

const refreshReport = () => {
    const current = selectedReport.value;
    selectedReport.value = '';
    setTimeout(() => selectedReport.value = current, 100);
}

onMounted(() => {
    loadReports();
});
</script>

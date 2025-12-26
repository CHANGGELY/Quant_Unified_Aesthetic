<template>
  <div class="h-full flex flex-col p-6">
      <AnalysisRunner
        title="选币相似度分析"
        description="计算多策略选币两两之间的相似度，并生成热力图。"
        :is-running="isRunning"
        :logs="logs"
        :report-url="reportUrl"
        @run="runAnalysis"
        @refresh="refreshReport"
      />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import AnalysisRunner from '../components/AnalysisRunner.vue';
import http from '@/common-module/services/http.provider';

const isRunning = ref(false);
const logs = ref<string[]>([]);
const reportUrl = ref<string | undefined>(undefined);

const runAnalysis = async () => {
  isRunning.value = true;
  logs.value = [];
  reportUrl.value = undefined;
  try {
    const res: any = await http.post('/qronos/analysis/similarity/run', false, {}, { baseUrl: '', timeoutSeconds: 600 });
    if (res.code === 200) {
        logs.value = res.data.logs;
        setReportUrl();
    } else {
        logs.value.push(`Error: ${res.msg}`);
    }
  } catch (e: any) {
    logs.value.push(`Error: ${e.message || e}`);
  } finally {
    isRunning.value = false;
  }
};

const setReportUrl = () => {
    const base = window.location.origin;
    reportUrl.value = `${base}/qronos/analysis/similarity/report/html?t=${Date.now()}`;
};

const refreshReport = () => {
    setReportUrl();
}
</script>

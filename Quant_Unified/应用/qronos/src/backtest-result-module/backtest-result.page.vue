<template>
  <div class="w-full h-full flex flex-col sm:flex-row overflow-hidden bg-gray-50 dark:bg-neutral-900">
    <!-- Sidebar List -->
    <div 
      class="flex-shrink-0 bg-white dark:bg-neutral-800 border-gray-200 dark:border-neutral-700 flex flex-col transition-all duration-300 ease-in-out overflow-hidden"
      :class="isSidebarOpen ? 'w-full sm:w-64 border-r' : 'w-0 border-none'"
    >
      <div class="p-4 border-b border-gray-200 dark:border-neutral-700 flex justify-between items-center">
        <h2 class="font-bold text-lg text-gray-800 dark:text-white">回测历史</h2>
        <div class="flex gap-1">
          <Button icon="pi pi-refresh" text rounded @click="loadReports" :loading="loading" v-tooltip="'刷新列表'" />
          <Button icon="pi pi-angle-left" text rounded @click="isSidebarOpen = false" v-tooltip="'折叠侧边栏'" />
        </div>
      </div>
      
      <div class="flex-1 overflow-y-auto p-2 space-y-2">
        <div 
          v-if="reports.length === 0" 
          class="text-center text-gray-500 py-4 text-sm"
        >
          暂无回测记录
        </div>
        
        <div
          v-for="report in reports"
          :key="report"
          @click="selectReport(report)"
          class="cursor-pointer p-3 rounded-lg transition-colors duration-200 flex items-center gap-2"
          :class="selectedReport === report ? 'bg-primary-100 dark:bg-primary-900/40 text-primary-700 dark:text-primary-100' : 'hover:bg-gray-100 dark:hover:bg-neutral-700 text-gray-700 dark:text-gray-200'"
        >
          <i class="pi pi-file text-sm"></i>
          <span class="truncate text-sm font-medium">{{ report }}</span>
        </div>
      </div>
    </div>

    <!-- Main Content (Iframe) -->
    <div class="flex-1 flex flex-col h-full overflow-hidden relative">
      <!-- Expand Button -->
      <div v-if="!isSidebarOpen" class="absolute left-4 top-4 z-50">
        <Button icon="pi pi-list" rounded severity="secondary" @click="isSidebarOpen = true" v-tooltip="'展开列表'" class="shadow-lg !bg-white dark:!bg-neutral-800 !border-gray-200 dark:!border-neutral-700" />
      </div>

      <div v-if="!selectedReport" class="flex-1 flex items-center justify-center flex-col gap-4 text-gray-400">
        <i class="pi pi-chart-line text-6xl opacity-20"></i>
        <p>请选择左侧的回测记录查看详情</p>
      </div>
      
      <div v-else class="flex-1 w-full h-full bg-white relative">
         <div v-if="iframeLoading" class="absolute inset-0 flex items-center justify-center bg-white/80 dark:bg-neutral-900/80 z-10">
            <i class="pi pi-spin pi-spinner text-4xl text-primary-500"></i>
         </div>
         <iframe 
            v-if="iframeSrc"
            :src="iframeSrc" 
            class="w-full h-full border-none"
            @load="onIframeLoad"
         ></iframe>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useToast } from 'primevue/usetoast';
import HttpProvider from '@/common-module/services/http.provider';
import Button from 'primevue/button';

const toast = useToast();
const reports = ref<string[]>([]);
const loading = ref(false);
const selectedReport = ref<string>('');
const iframeLoading = ref(false);
const isSidebarOpen = ref(true);

const loadReports = async () => {
  loading.value = true;
  try {
    // Note: HttpProvider.get automatically adds base URL (e.g. /flask or /api)
    // We use isAPI=false to use flaskBaseUrl
    const res = await HttpProvider.get('/backtest/reports', false);
    const data = res.data;
    if (data.code === 200) {
      reports.value = data.data;
      // Auto select first report if none selected and list not empty
      if (!selectedReport.value && reports.value.length > 0) {
        selectReport(reports.value[0]);
      }
    } else {
      toast.add({ severity: 'error', summary: 'Error', detail: data.msg });
    }
  } catch (e: any) {
    console.error(e);
  } finally {
    loading.value = false;
  }
};

const selectReport = (report: string) => {
  if (selectedReport.value === report) return;
  selectedReport.value = report;
  iframeLoading.value = true;
};

const iframeSrc = computed(() => {
  if (!selectedReport.value) return '';
  // Construct the URL. 
  // In dev: /flask/backtest/report/{name}/html -> proxied to backend
  // In prod: /qronos/backtest/report/{name}/html (nginx handles /qronos)
  
  // Check if we are in dev mode
  const isDev = import.meta.env.VITE_APP_ENV === "development";
  
  if (isDev) {
      return `/flask/backtest/report/${selectedReport.value}/html`;
  } else {
      const baseElement = document.querySelector("base");
      let prefix = "";
      if (baseElement && baseElement.href) {
        const url = new URL(baseElement.href);
        prefix = url.pathname.replace(/^\/|\/$/g, "");
      }
      return prefix ? `/${prefix}/backtest/report/${selectedReport.value}/html` : `/flask/backtest/report/${selectedReport.value}/html`;
  }
});

const onIframeLoad = () => {
  iframeLoading.value = false;
};

onMounted(() => {
  loadReports();
});
</script>

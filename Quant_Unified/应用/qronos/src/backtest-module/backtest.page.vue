<template>
  <div class="w-full p-2 sm:p-6 flex flex-col gap-4">
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-bold text-gray-800 dark:text-white">回测中心</h1>
      <div class="flex gap-2">
        <Button label="保存配置" icon="pi pi-save" @click="saveConfig" :loading="saving" />
        <Button label="开始回测" icon="pi pi-play" severity="success" @click="runBacktest" :loading="running" />
      </div>
    </div>

    <div class="flex flex-col sm:flex-row gap-4">
      <!-- Config Editor -->
      <Card class="flex-1">
        <template #title>配置参数 (config.py)</template>
        <template #content>
          <textarea
            v-model="configContent"
            class="w-full h-[75vh] p-4 font-mono text-sm bg-gray-50 dark:bg-neutral-900 border rounded resize-none focus:outline-none focus:ring-2 focus:ring-primary-500"
            spellcheck="false"
          ></textarea>
        </template>
      </Card>

      <!-- Logs / Output -->
      <Card class="flex-1">
        <template #title>运行日志</template>
        <template #content>
          <div class="bg-black text-green-400 p-4 h-[75vh] overflow-auto font-mono text-xs rounded" ref="logContainer">
            <div v-if="logs.length === 0" class="text-gray-500">暂无日志...</div>
            <div v-for="(log, index) in logs" :key="index" class="whitespace-pre-wrap">{{ log }}</div>
          </div>
        </template>
      </Card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useToast } from 'primevue/usetoast';
import HttpProvider from '@/common-module/services/http.provider';
import Button from 'primevue/button';
import Card from 'primevue/card';

const toast = useToast();
const configContent = ref('');
const logs = ref<string[]>([]);
const saving = ref(false);
const running = ref(false);
const logContainer = ref<HTMLElement | null>(null);

const loadConfig = async () => {
  try {
    const res = await HttpProvider.get('/backtest/config', false);
    const data = res.data;
    if (data.code === 200) {
        configContent.value = data.data.content;
    } else {
        toast.add({ severity: 'error', summary: 'Error', detail: data.msg });
    }
  } catch (e: any) {
    console.error(e);
    // HttpProvider already emits global error, but we can add toast if needed
  }
};

const saveConfig = async () => {
  saving.value = true;
  try {
    const res = await HttpProvider.post('/backtest/config', false, { content: configContent.value });
    const data = res.data;
    if (data.code === 200) {
        toast.add({ severity: 'success', summary: 'Success', detail: 'Config saved' });
    } else {
        toast.add({ severity: 'error', summary: 'Error', detail: data.msg });
    }
  } catch (e: any) {
    // Error handled by HttpProvider
  } finally {
    saving.value = false;
  }
};

const runBacktest = async () => {
  running.value = true;
  logs.value = ['Starting backtest...'];
  try {
    const res = await HttpProvider.post('/backtest/run', false, {});
    const data = res.data;
    if (data.code === 200) {
        toast.add({ severity: 'info', summary: 'Started', detail: 'Backtest started' });
        pollStatus();
    } else {
        toast.add({ severity: 'error', summary: 'Error', detail: data.msg });
        running.value = false;
    }
  } catch (e: any) {
    running.value = false;
  }
};

const pollStatus = async () => {
    const interval = setInterval(async () => {
        try {
            const resStatus = await HttpProvider.get('/backtest/status', false);
            const dataStatus = resStatus.data;
            
            // Fetch logs regardless of status
            const resLogs = await HttpProvider.get('/backtest/logs', false);
            const dataLogs = resLogs.data;
            if (dataLogs.code === 200) {
                logs.value = dataLogs.data;
                // Auto scroll to bottom
                if (logContainer.value) {
                    setTimeout(() => {
                        logContainer.value!.scrollTop = logContainer.value!.scrollHeight;
                    }, 0);
                }
            }

            if (!dataStatus.data.is_running) {
                running.value = false;
                clearInterval(interval);
            }
        } catch (e) {
            running.value = false;
            clearInterval(interval);
        }
    }, 1000);
};

onMounted(() => {
  loadConfig();
});
</script>

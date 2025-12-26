<template>
  <aside
    :class="[
      'h-full hidden sm:flex flex-col justify-between bg-gradient-to-b from-white/90 to-gray-100 dark:from-neutral-900 dark:to-neutral-800 shadow-xl z-40  transition-all duration-100',
      viewExpanded ? 'w-45 p-3 ' : 'w-20 p-3',
    ]"
  >
    <div class="space-y-4">
      <div
        class="flex items-center justify-center gap-2"
        @click="toggleSidebar"
      >
        <span
          v-show="viewExpanded"
          :class="[
            'cursor-pointer font-bold text-lg text-gray-800 dark:text-white transition-all duration-150 origin-left inline-block truncate',
            viewExpanded
              ? 'opacity-100 translate-x-0 scale-100'
              : 'opacity-0 -translate-x-4 scale-95 pointer-events-none',
          ]"
        >
          实盘网页版
        </span>
        <div class="flex shrink-0 items-center cursor-pointer">
          <img
            class="h-10 w-auto"
            src="@/assets/header-img/xbx-logo.png"
            alt="Your Company"
          />
        </div>
      </div>
      <Divider class="my-0" v-if="store.isBoundGA === true" />
      <div class="py-4 flex flex-col gap-2">
        <template v-if="store.isBoundGA === true">
          <div
            v-for="item in viewMenu"
            :key="item.label"
            class="flex items-center group px-0.5"
          >
            <button
              class="cursor-pointer flex items-center w-full gap-2 p-2 rounded-xl transition-all duration-150 hover:bg-primary-50 dark:hover:bg-primary-900/30 group-active:bg-primary-100 dark:group-active:bg-primary-900/40"
              :class="
                viewSelected === item.route
                  ? 'bg-primary-100 dark:bg-primary-900/40 text-primary-600 dark:text-primary-100 font-semibold shadow'
                  : 'text-gray-700 dark:text-gray-200'
              "
              @click="menuClick(item)"
              v-tooltip.right="!viewExpanded ? item.label : ''"
            >
              <span
                class="flex items-center justify-center w-9 h-9 rounded-full transition-all duration-150"
                :class="
                  viewSelected === item.route
                    ? 'bg-primary-200 dark:bg-primary-800'
                    : 'bg-gray-100 dark:bg-neutral-800 group-hover:bg-primary-100 dark:group-hover:bg-primary-900/40'
                "
              >
                <i :class="item.icon" class="text-lg"></i>
              </span>
              <span v-if="viewExpanded" class="truncate">{{ item.label }}</span>
            </button>
          </div>
        </template>
      </div>
    </div>
    <div class="flex flex-col gap-4">
      <div
        class="flex flex-col items-center gap-2"
        :class="viewExpanded ? `flex-row justify-center` : ``"
      >
        <PrimaryConfiguratorTemplate />
      </div>
      <div class="flex justify-center items-center gap-4">
        <div v-if="viewExpanded">
          <Message severity="secondary" class="h-6 font-mono"
            >v{{ store.version }}</Message
          >
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import { useToast } from "primevue/usetoast";
const toast = useToast();
import { useRouter, useRoute } from "vue-router";
const router = useRouter();
const route = useRoute();
import { useUserStore } from "@/store/user";
const store = useUserStore();

 
import PrimaryConfiguratorTemplate from "@/layout-module/components/primaryConfigurator.template.vue";
const defaultAvatar =
  "https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?ixlib=rb-1.2.1&ixid=eyJhcHBfaWQiOjEyMDd9&auto=format&fit=facearea&facepad=2&w=256&h=256&q=80";

const viewMenu = ref([
  { label: "首页", icon: "pi pi-home", route: "/home" },
  { label: "数据中心", icon: "pi pi-database", route: "/dataCenter" },
  { label: "策略中心", icon: "pi pi-code", route: "/strategyCenter" },
  { label: "回测中心", icon: "pi pi-replay", route: "/backtestCenter" },
  { label: "回测结果", icon: "pi pi-chart-line", route: "/backtestResult" },
  { label: "因子分析", icon: "pi pi-chart-bar", route: "/analysis/factor" },
  { label: "选币相似度", icon: "pi pi-th-large", route: "/analysis/similarity" },
  { label: "曲线相关性", icon: "pi pi-sliders-h", route: "/analysis/correlation" },
]);

 

const viewExpanded = ref(false);
const viewSelected = ref("");

// 监听路由变化，同步 viewSelected
watch(
  () => route.path,
  (newPath) => {
    const matchedMenu = viewMenu.value.find((item) => {
      if (item.route === "/strategyCenter") {
        // 策略中心页面特殊处理
        return newPath.startsWith("/strategyCenter");
      }
      return item.route === newPath;
    });
    if (matchedMenu) {
      viewSelected.value = matchedMenu.route;
    }
  },
  { immediate: true }
);

const toggleSidebar = () => {
  viewExpanded.value = !viewExpanded.value;
};

const menuClick = (item: any) => {
  router.push(item.route);
};

 
</script>

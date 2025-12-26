import { createRouter, createWebHistory } from "vue-router";
const LayoutPage = () => import("@/layout-module/layout.page.vue");
const HomePage = () => import("@/home-module/home.page.vue");
const DataCenterPage = () =>
  import("@/data-center-module/data-center.page.vue");
const StrategyCenterPage = () =>
  import("@/strategy-center-module/strategy-center.page.vue");
const BacktestPage = () => import("@/backtest-module/backtest.page.vue");
const BacktestResultPage = () => import("@/backtest-result-module/backtest-result.page.vue");
const FactorAnalysisPage = () => import("@/analysis-module/pages/FactorAnalysis.page.vue");
const SimilarityAnalysisPage = () => import("@/analysis-module/pages/SimilarityAnalysis.page.vue");
const CorrelationAnalysisPage = () => import("@/analysis-module/pages/CorrelationAnalysis.page.vue");

import { useStorageValueOrFn } from "@/common-module/hooks/getOrSetStorage";
const { sessionGAtoken, userInfo } = useStorageValueOrFn();

// 动态获取 base URL
const getBaseUrl = (): string => {
  // 首先尝试从 HTML base 标签获取（nginx 会动态设置）
  const baseElement = document.querySelector("base");
  if (baseElement && baseElement.href) {
    const url = new URL(baseElement.href);
    return url.pathname;
  }

  // fallback 到 Vite 的 BASE_URL
  return import.meta.env.BASE_URL || "/";
};

import { syncDarkClass } from "@/main";

const appRouter = createRouter({
  history: createWebHistory(getBaseUrl()), // [mk] use history mode
  routes: [
    {
      path: "/",
      component: LayoutPage,
      children: [
        {
          path: "/",
          redirect: { path: "/home" },
        },
        
        {
          path: "/home",
          component: HomePage,
          meta: {
            title: "首页",
            auth: true,
            header: true,
          },
        },
        {
          path: "/dataCenter",
          component: DataCenterPage,
          meta: {
            title: "数据中心",
            auth: true,
            header: true,
          },
        },
        {
          path: "/strategyCenter/:id?",
          component: StrategyCenterPage,
          meta: {
            title: "策略中心",
            auth: true,
            header: true,
          },
        },
        {
          path: "/backtestCenter",
          component: BacktestPage,
          meta: {
            title: "回测中心",
            auth: true,
            header: true,
          },
        },
        {
          path: "/backtestResult",
          component: BacktestResultPage,
          meta: {
            title: "回测结果",
            auth: true,
            header: true,
          },
        },
        {
          path: "/analysis/factor",
          component: FactorAnalysisPage,
          meta: {
            title: "因子分析",
            auth: true,
            header: true,
          },
        },
        {
          path: "/analysis/similarity",
          component: SimilarityAnalysisPage,
          meta: {
            title: "选币相似度",
            auth: true,
            header: true,
          },
        },
        {
          path: "/analysis/correlation",
          component: CorrelationAnalysisPage,
          meta: {
            title: "曲线相关性",
            auth: true,
            header: true,
          },
        },
        
      ],
    },
  ],
});

export default appRouter;

appRouter.beforeEach(async (to, from, next) => {
  if (to.matched.length === 0) {
    next("/home");
    return;
  }
  next();
});

appRouter.afterEach((to, from) => {
  syncDarkClass();
});

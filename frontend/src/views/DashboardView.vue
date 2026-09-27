<template>
  <div class="dashboard-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Сводка операций</h1>
        <p class="page-subtitle">Реальные агрегированные метрики базы данных (SQL GROUP BY)</p>
      </div>
      <n-button type="primary" secondary :loading="loading" @click="fetchMetrics">
        <template #icon>🔄</template>
        Обновить
      </n-button>
    </div>

    <!-- Error state -->
    <n-alert v-if="error" type="error" style="margin-bottom: 24px" closable @close="error = ''">
      {{ error }}
    </n-alert>

    <!-- Metrics Cards Grid -->
    <n-spin :show="loading">
      <n-grid cols="1 s:2 m:3 l:6" responsive="screen" :x-gap="16" :y-gap="16">
        <n-gi>
          <n-card class="stat-card" size="small">
            <n-statistic label="Всего задач" :value="metrics.total_tasks">
              <template #prefix>📦</template>
            </n-statistic>
          </n-card>
        </n-gi>

        <n-gi>
          <n-card class="stat-card" size="small">
            <n-statistic label="В очереди" :value="metrics.pending">
              <template #prefix>⏳</template>
            </n-statistic>
          </n-card>
        </n-gi>

        <n-gi>
          <n-card class="stat-card" size="small">
            <n-statistic label="В обработке" :value="metrics.processing">
              <template #prefix>⚙️</template>
            </n-statistic>
          </n-card>
        </n-gi>

        <n-gi>
          <n-card class="stat-card" size="small">
            <n-statistic label="На проверке" :value="metrics.in_review">
              <template #prefix>🔍</template>
            </n-statistic>
          </n-card>
        </n-gi>

        <n-gi>
          <n-card class="stat-card" size="small">
            <n-statistic label="Завершено" :value="metrics.completed">
              <template #prefix>✅</template>
            </n-statistic>
          </n-card>
        </n-gi>

        <n-gi>
          <n-card class="stat-card" size="small">
            <n-statistic label="Ошибки" :value="metrics.failed">
              <template #prefix>⚠️</template>
            </n-statistic>
          </n-card>
        </n-gi>
      </n-grid>

      <!-- Key SaaS Metric Highlight -->
      <n-card class="highlight-card" style="margin-top: 24px">
        <div class="highlight-content">
          <div class="highlight-info">
            <h3>⚡ Автоматизировано без человека (Straight-Through)</h3>
            <p>
              Количество задач с высокой степенью уверенности (Confidence >= порога),
              выполненных полностью автономно без вмешательства оператора.
            </p>
          </div>
          <div class="highlight-number">
            {{ metrics.automated_without_human }}
            <span class="highlight-label">из {{ metrics.completed }} завершенных</span>
          </div>
        </div>
      </n-card>
    </n-spin>

    <!-- Quick action links -->
    <n-grid cols="1 m:2" responsive="screen" :x-gap="16" :y-gap="16" style="margin-top: 24px">
      <n-gi>
        <n-card title="Очередь задач" size="small">
          <p>Просмотр всех фоновых пайплайнов, фильтрация по типам и статусам.</p>
          <n-button type="primary" secondary block @click="$router.push('/tasks')">
            Перейти к списку задач →
          </n-button>
        </n-card>
      </n-gi>
      <n-gi>
        <n-card title="Human-in-the-Loop Review" size="small">
          <p>
            Задачи с низкой уверенностью (confidence &lt; threshold), требующие
            верификации, одобрения или корректировки бухгалтером.
          </p>
          <n-button type="warning" secondary block @click="$router.push('/review')">
            Проверить спорные задачи ({{ metrics.in_review }}) →
          </n-button>
        </n-card>
      </n-gi>
    </n-grid>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import {
  NGrid,
  NGi,
  NCard,
  NStatistic,
  NButton,
  NAlert,
  NSpin,
} from 'naive-ui';
import { apiClient } from '@/api/client';
import type { DashboardMetrics } from '@/types';

const loading = ref(false);
const error = ref('');
const metrics = ref<DashboardMetrics>({
  total_tasks: 0,
  pending: 0,
  processing: 0,
  in_review: 0,
  completed: 0,
  failed: 0,
  automated_without_human: 0,
});

const fetchMetrics = async () => {
  loading.value = true;
  error.value = '';
  try {
    const resp = await apiClient.get<DashboardMetrics>('/dashboard/metrics');
    metrics.value = resp.data;
  } catch (err: any) {
    error.value = err.message || 'Не удалось загрузить метрики дашборда';
  } finally {
    loading.value = false;
  }
};

onMounted(() => {
  fetchMetrics();
});
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
}

.page-subtitle {
  margin: 4px 0 0 0;
  font-size: 13px;
  opacity: 0.7;
}

.stat-card {
  border-radius: 8px;
}

.highlight-card {
  border-left: 4px solid #18a058;
}

.highlight-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.highlight-info h3 {
  margin: 0 0 6px 0;
  font-size: 16px;
  font-weight: 600;
}

.highlight-info p {
  margin: 0;
  font-size: 13px;
  opacity: 0.75;
}

.highlight-number {
  font-size: 36px;
  font-weight: 800;
  color: #18a058;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.highlight-label {
  font-size: 12px;
  font-weight: normal;
  opacity: 0.7;
}
</style>

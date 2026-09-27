<template>
  <div class="settings-page">
    <div class="page-header">
      <h1 class="page-title">Настройки и статус системы</h1>
      <p class="page-subtitle">Параметры окружения, мультиарендность (Multi-Tenancy) и статус AI-провайдера</p>
    </div>

    <n-grid cols="1 m:2" responsive="screen" :x-gap="16" :y-gap="16">
      <n-gi>
        <n-card title="Текущий пользователь и организация" size="small">
          <n-descriptions bordered :column="1">
            <n-descriptions-item label="ФИО">
              {{ authStore.user?.full_name }}
            </n-descriptions-item>
            <n-descriptions-item label="Email">
              {{ authStore.user?.email }}
            </n-descriptions-item>
            <n-descriptions-item label="Роль">
              <n-tag :type="authStore.user?.role === 'admin' ? 'info' : 'default'">
                {{ authStore.user?.role?.toUpperCase() }}
              </n-tag>
            </n-descriptions-item>
            <n-descriptions-item label="Organization ID (Multi-Tenancy Tenant)">
              <code>{{ authStore.user?.organization_id }}</code>
            </n-descriptions-item>
            <n-descriptions-item label="Статус аккаунта">
              <n-tag type="success">Активен</n-tag>
            </n-descriptions-item>
          </n-descriptions>
        </n-card>
      </n-gi>

      <n-gi>
        <n-card title="Конфигурация ядра SaaS (Foundation Config)" size="small">
          <n-descriptions bordered :column="1">
            <n-descriptions-item label="Статус Healthcheck (/health)">
              <n-tag :type="healthStatus?.status === 'healthy' ? 'success' : 'error'">
                {{ healthStatus?.status || 'Проверка...' }}
              </n-tag>
            </n-descriptions-item>
            <n-descriptions-item label="База данных">
              {{ healthStatus?.database || 'Подключена' }}
            </n-descriptions-item>
            <n-descriptions-item label="Режим Demo Mode">
              <n-tag :type="healthStatus?.demo_mode ? 'warning' : 'success'">
                {{ healthStatus?.demo_mode ? 'Включен (DEMO_MODE=true)' : 'Production' }}
              </n-tag>
            </n-descriptions-item>
            <n-descriptions-item label="Активный AI Provider">
              <n-tag type="info">
                {{ healthStatus?.ai_provider === 'demo' ? 'DemoAIProvider (Детерминированный)' : 'LLMProvider' }}
              </n-tag>
            </n-descriptions-item>
            <n-descriptions-item label="Порог Human Review (REVIEW_CONFIDENCE_THRESHOLD)">
              <strong>{{ (healthStatus?.review_threshold * 100).toFixed(0) }}%</strong>
              (значение: {{ healthStatus?.review_threshold }})
            </n-descriptions-item>
          </n-descriptions>
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
  NDescriptions,
  NDescriptionsItem,
  NTag,
} from 'naive-ui';
import axios from 'axios';
import { useAuthStore } from '@/stores/auth';

const authStore = useAuthStore();
const healthStatus = ref<any>(null);

const fetchHealth = async () => {
  try {
    const resp = await axios.get('/health');
    healthStatus.value = resp.data;
  } catch (err: any) {
    healthStatus.value = { status: 'error', database: 'unavailable' };
  }
};

onMounted(() => {
  fetchHealth();
});
</script>

<style scoped>
.page-header {
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
</style>

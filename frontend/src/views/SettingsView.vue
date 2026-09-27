<template>
  <div class="settings-page">
    <div class="page-header">
      <h1 class="page-title">Настройки и статус системы</h1>
      <p class="page-subtitle">Параметры окружения, мультиарендность (Multi-Tenancy) и интеграция с 1С</p>
    </div>

    <n-grid cols="1 m:2" responsive="screen" :x-gap="16" :y-gap="16">
      <!-- 1. Current user & organization -->
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

      <!-- 2. SaaS Core Foundation Status -->
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
            <n-descriptions-item label="Порог Human Review">
              <strong>{{ (healthStatus?.review_threshold * 100 || 85).toFixed(0) }}%</strong>
              (значение: {{ healthStatus?.review_threshold || 0.85 }})
            </n-descriptions-item>
          </n-descriptions>
        </n-card>
      </n-gi>

      <!-- 3. 1C:Enterprise Connection & Security Settings -->
      <n-gi span="1 m:2">
        <n-card title="Подключение к 1С:Предприятие (1C OData)" size="small">
          <template #header-extra>
            <n-tag :type="onecConn?.is_mock ? 'warning' : 'success'" round size="small">
              {{ onecConn?.is_mock ? '⚡ Mock Режим (Эмуляция)' : '🟢 OData Подключено' }}
            </n-tag>
          </template>

          <n-grid cols="1 m:2" responsive="screen" :x-gap="16" :y-gap="16">
            <!-- Left column: Read-only summary -->
            <n-gi>
              <h4 style="margin: 0 0 12px 0;">Текущее состояние</h4>
              <n-descriptions bordered :column="1">
                <n-descriptions-item label="OData Base URL">
                  <code>{{ onecConn?.base_url || 'Не задан (используются mock-данные)' }}</code>
                </n-descriptions-item>
                <n-descriptions-item label="Пользователь 1С">
                  {{ onecConn?.username || '—' }}
                </n-descriptions-item>
                <n-descriptions-item label="Режим записи">
                  <n-tag :type="onecConn?.is_writable ? 'warning' : 'info'" size="small">
                    {{ onecConn?.is_writable ? 'Разрешена запись (черновики)' : 'Строгий Read-Only (L0-L2)' }}
                  </n-tag>
                </n-descriptions-item>
                <n-descriptions-item label="Потолок риска организации">
                  <n-tag type="default" size="small">
                    {{ onecConn?.max_onec_risk_level || 'Глобальный (ANALYTICS_READ)' }}
                  </n-tag>
                </n-descriptions-item>
              </n-descriptions>

              <div style="margin-top: 16px;">
                <n-button
                  type="info"
                  secondary
                  :loading="testingConnection"
                  @click="testSavedConnection"
                >
                  Проверить связь (Health Check)
                </n-button>
              </div>

              <div v-if="testResult" style="margin-top: 12px;">
                <n-alert
                  :type="testResult.status === 'connected' ? 'success' : 'warning'"
                  :title="testResult.status === 'connected' ? 'Связь с 1С установлена' : 'Ответ 1С'"
                  closable
                  @close="testResult = null"
                >
                  <pre style="margin: 0; font-size: 11px;">{{ JSON.stringify(testResult, null, 2) }}</pre>
                </n-alert>
              </div>
            </n-gi>

            <!-- Right column: Admin Configuration Form -->
            <n-gi>
              <div v-if="isAdmin">
                <h4 style="margin: 0 0 12px 0;">Управление подключением (только для Администратора)</h4>
                <n-form ref="formRef" :model="form" size="small" label-placement="top">
                  <n-form-item label="1C OData Base URL (Защищен от SSRF)">
                    <n-input
                      v-model:value="form.base_url"
                      placeholder="https://onec-server.company.kz/trade/odata/standard.odata"
                    />
                  </n-form-item>

                  <n-grid cols="1 m:2" :x-gap="12">
                    <n-gi>
                      <n-form-item label="Логин (1С OData User)">
                        <n-input v-model:value="form.username" placeholder="web_service_user" />
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                      <n-form-item label="Пароль (Шифруется Fernet)">
                        <n-input
                          v-model:value="form.password"
                          type="password"
                          show-password-on="click"
                          placeholder="Оставьте пустым для сохранения прежнего"
                        />
                      </n-form-item>
                    </n-gi>
                  </n-grid>

                  <n-grid cols="1 m:2" :x-gap="12">
                    <n-gi>
                      <n-form-item label="Потолок риска для тенанта">
                        <n-select
                          v-model:value="form.max_onec_risk_level"
                          :options="riskLevelOptions"
                          placeholder="Выберите риск-потолок"
                          clearable
                        />
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                      <n-form-item label="Разрешить запись">
                        <n-switch v-model:value="form.is_writable">
                          <template #checked>Запись разрешена</template>
                          <template #unchecked>Read-Only</template>
                        </n-switch>
                      </n-form-item>
                    </n-gi>
                  </n-grid>

                  <div style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 8px;">
                    <n-button
                      type="primary"
                      :loading="savingConfig"
                      @click="saveOnecConfig"
                    >
                      Сохранить настройки 1С
                    </n-button>
                  </div>
                </n-form>
              </div>
              <div v-else>
                <n-alert type="info" title="Ограничение прав">
                  Изменение параметров подключения к 1С и учетных записей OData доступно только пользователям с ролью ADMIN.
                </n-alert>
              </div>
            </n-gi>
          </n-grid>
        </n-card>
      </n-gi>
    </n-grid>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import {
  NGrid,
  NGi,
  NCard,
  NDescriptions,
  NDescriptionsItem,
  NTag,
  NButton,
  NAlert,
  NForm,
  NFormItem,
  NInput,
  NSwitch,
  NSelect,
  useMessage,
} from 'naive-ui';
import axios from 'axios';
import api from '@/api/client';
import { useAuthStore } from '@/stores/auth';

const authStore = useAuthStore();
const message = useMessage();

const healthStatus = ref<any>(null);
const onecConn = ref<any>(null);
const testingConnection = ref(false);
const testResult = ref<any>(null);
const savingConfig = ref(false);

const isAdmin = computed(() => authStore.user?.role === 'admin');

const form = ref({
  base_url: '',
  username: '',
  password: '',
  is_writable: false,
  max_onec_risk_level: null as string | null,
});

const riskLevelOptions = [
  { label: 'L0: SAFE_READ (Только справочники и статус)', value: 'SAFE_READ' },
  { label: 'L1: ANALYTICS_READ (Остатки, задолженности)', value: 'ANALYTICS_READ' },
  { label: 'L2: SENSITIVE_READ (Зарплаты, выписки)', value: 'SENSITIVE_READ' },
];

const fetchHealth = async () => {
  try {
    const resp = await axios.get('/health');
    healthStatus.value = resp.data;
  } catch {
    healthStatus.value = { status: 'error', database: 'unavailable' };
  }
};

const fetchOnecConnection = async () => {
  try {
    const resp = await api.get('/onec-connection');
    onecConn.value = resp.data;
    form.value.base_url = resp.data.base_url || '';
    form.value.username = resp.data.username || '';
    form.value.is_writable = resp.data.is_writable || false;
    form.value.max_onec_risk_level = resp.data.max_onec_risk_level || null;
  } catch (err: any) {
    console.error('Failed to load 1C connection status:', err);
  }
};

const testSavedConnection = async () => {
  testingConnection.value = true;
  testResult.value = null;
  try {
    const resp = await api.post('/onec-connection/test-connection', {});
    testResult.value = resp.data;
    message.success('Проверка связи с 1С успешно завершена');
  } catch (err: any) {
    testResult.value = { error: err.response?.data?.detail || err.message };
    message.error('Связь с 1С недоступна');
  } finally {
    testingConnection.value = false;
  }
};

const saveOnecConfig = async () => {
  if (!form.value.base_url) {
    message.warning('Укажите Base URL сервиса 1C OData');
    return;
  }
  savingConfig.value = true;
  try {
    const payload: any = {
      base_url: form.value.base_url,
      username: form.value.username || null,
      is_writable: form.value.is_writable,
      max_onec_risk_level: form.value.max_onec_risk_level || null,
    };
    if (form.value.password) {
      payload.password = form.value.password;
    }
    const resp = await api.put('/onec-connection', payload);
    onecConn.value = resp.data;
    form.value.password = '';
    message.success('Параметры подключения к 1С сохранены');
  } catch (err: any) {
    const detail = err.response?.data?.detail || err.message;
    message.error(`Ошибка сохранения: ${detail}`);
  } finally {
    savingConfig.value = false;
  }
};

onMounted(() => {
  fetchHealth();
  fetchOnecConnection();
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

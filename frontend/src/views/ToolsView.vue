<template>
  <div class="tools-page">
    <div class="page-header">
      <h1 class="page-title">Реестр инструментов 1С и аудит</h1>
      <p class="page-subtitle">
        Типизированный Tool Registry, проверка политик безопасности (L0–L5), Dry-Run симуляция и журнал вызовов
      </p>
    </div>

    <!-- Section 1: Available Tools Registry -->
    <n-card title="Доступные инструменты 1С:Предприятие (Tool Registry)" size="small" style="margin-bottom: 24px;">
      <template #header-extra>
        <n-button size="small" secondary @click="fetchTools" :loading="loadingTools">
          Обновить реестр
        </n-button>
      </template>

      <n-spin :show="loadingTools">
        <n-grid cols="1 m:2" responsive="screen" :x-gap="16" :y-gap="16">
          <n-gi v-for="tool in tools" :key="tool.name">
            <n-card embedded size="small" :title="tool.name" class="tool-card">
              <template #header-extra>
                <div style="display: flex; gap: 6px; align-items: center;">
                  <n-tag :type="getRiskTagType(tool.risk_level)" size="small">
                    {{ tool.risk_level }}
                  </n-tag>
                  <n-tag v-if="tool.is_mutating" type="error" size="small">
                    Запись
                  </n-tag>
                  <n-tag v-else type="default" size="small">
                    Read-Only
                  </n-tag>
                </div>
              </template>

              <p class="tool-description">{{ tool.description }}</p>

              <n-descriptions bordered size="small" :column="1" style="margin-top: 8px;">
                <n-descriptions-item label="Форма результата">
                  <span style="font-size: 12px;">{{ tool.output_summary }}</span>
                </n-descriptions-item>
              </n-descriptions>

              <div class="tool-actions">
                <n-button
                  size="small"
                  type="info"
                  secondary
                  @click="openRunModal(tool, true)"
                >
                  🧪 Dry-Run (Тест)
                </n-button>
                <n-button
                  size="small"
                  type="primary"
                  secondary
                  @click="openRunModal(tool, false)"
                >
                  ▶ Выполнить
                </n-button>
              </div>
            </n-card>
          </n-gi>
        </n-grid>
      </n-spin>
    </n-card>

    <!-- Section 2: Execution History / Audit Telemetry -->
    <n-card title="История выполнения инструментов (Telemetry & Audit Logs)" size="small">
      <template #header-extra>
        <n-button size="small" secondary @click="fetchHistory" :loading="loadingHistory">
          Обновить историю
        </n-button>
      </template>

      <n-data-table
        :columns="historyColumns"
        :data="historyData"
        :loading="loadingHistory"
        :pagination="pagination"
        size="small"
      />
    </n-card>

    <!-- Execution Modal -->
    <n-modal
      v-model:show="showRunModal"
      preset="card"
      :title="`Запуск инструмента: ${activeTool?.name} (${isDryRun ? 'DRY-RUN' : 'РЕАЛЬНЫЙ ВЫЗОВ'})`"
      style="width: 600px; max-width: 90vw;"
    >
      <div>
        <p style="margin-top: 0; font-size: 13px;">{{ activeTool?.description }}</p>

        <n-form size="small" label-placement="top">
          <n-form-item label="Параметры вызова (JSON)">
            <n-input
              v-model:value="paramsJson"
              type="textarea"
              :rows="4"
              placeholder="{}"
              font-family="monospace"
            />
          </n-form-item>
        </n-form>

        <div v-if="executionResult" style="margin-top: 16px;">
          <n-alert
            :type="executionResult.error ? 'error' : 'success'"
            :title="executionResult.error ? 'Ошибка выполнения' : 'Результат выполнения'"
            style="margin-bottom: 8px;"
          >
            <div v-if="executionResult.error">
              <div>{{ executionResult.error }}</div>
              <div v-if="executionResult.error_code" style="font-size: 11px; margin-top: 4px; opacity: 0.9;">
                Код ошибки: <strong>{{ executionResult.error_code }}</strong>
                <span v-if="executionResult.request_id"> | Request ID: <code>{{ executionResult.request_id }}</code></span>
              </div>
            </div>
            <div v-else>
              <div>
                Риск: {{ executionResult.risk_level }} |
                Режим: {{ executionResult.dry_run ? 'Dry Run' : 'Executed' }} |
                Mock: {{ executionResult.is_mock }}
              </div>
              <div v-if="executionResult.request_id" style="font-size: 11px; margin-top: 4px; opacity: 0.9;">
                Request ID: <code>{{ executionResult.request_id }}</code>
              </div>
            </div>
          </n-alert>

          <pre class="result-box">{{ JSON.stringify(executionResult.data || executionResult, null, 2) }}</pre>
        </div>
      </div>

      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px;">
          <n-button @click="showRunModal = false">Закрыть</n-button>
          <n-button
            :type="isDryRun ? 'info' : 'primary'"
            :loading="executing"
            @click="submitExecution"
          >
            {{ isDryRun ? 'Запустить Dry-Run' : 'Подтвердить выполнение' }}
          </n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, h, onMounted } from 'vue';
import {
  NGrid,
  NGi,
  NCard,
  NDescriptions,
  NDescriptionsItem,
  NTag,
  NButton,
  NSpin,
  NDataTable,
  NModal,
  NForm,
  NFormItem,
  NInput,
  NAlert,
  useMessage,
} from 'naive-ui';
import api from '@/api/client';

const message = useMessage();

const tools = ref<any[]>([]);
const loadingTools = ref(false);
const historyData = ref<any[]>([]);
const loadingHistory = ref(false);

const pagination = { pageSize: 10 };

const showRunModal = ref(false);
const activeTool = ref<any>(null);
const isDryRun = ref(true);
const paramsJson = ref('{}');
const executing = ref(false);
const executionResult = ref<any>(null);

const getRiskTagType = (risk: string) => {
  switch (risk) {
    case 'SAFE_READ':
      return 'default';
    case 'ANALYTICS_READ':
      return 'info';
    case 'SENSITIVE_READ':
      return 'warning';
    case 'WRITE_DRAFT':
    case 'WRITE_POST':
    case 'DESTRUCTIVE':
      return 'error';
    default:
      return 'default';
  }
};

const historyColumns = [
  {
    title: 'Время',
    key: 'created_at',
    width: 170,
    render(row: any) {
      return new Date(row.created_at).toLocaleString('ru-RU');
    },
  },
  {
    title: 'Инструмент',
    key: 'tool_name',
    render(row: any) {
      return h('code', { style: { fontSize: '12px' } }, row.tool_name);
    },
  },
  {
    title: 'Уровень риска',
    key: 'risk_level',
    width: 150,
    render(row: any) {
      return h(
        NTag,
        { size: 'small', type: getRiskTagType(row.risk_level) },
        { default: () => row.risk_level }
      );
    },
  },
  {
    title: 'Тип',
    key: 'is_dry_run',
    width: 110,
    render(row: any) {
      return h(
        NTag,
        { size: 'small', type: row.is_dry_run ? 'warning' : 'success' },
        { default: () => (row.is_dry_run ? 'Dry Run' : 'Real Call') }
      );
    },
  },
  {
    title: 'Статус',
    key: 'status',
    width: 110,
    render(row: any) {
      const type =
        row.status === 'SUCCESS'
          ? 'success'
          : row.status === 'BLOCKED'
          ? 'warning'
          : 'error';
      return h(NTag, { size: 'small', type }, { default: () => row.status });
    },
  },
  {
    title: 'Код ошибки',
    key: 'error_code',
    width: 150,
    render(row: any) {
      if (!row.error_code) return '—';
      return h(NTag, { size: 'small', type: 'error' }, { default: () => row.error_code });
    },
  },
  {
    title: 'Latency',
    key: 'latency_ms',
    width: 90,
    render(row: any) {
      return row.latency_ms != null ? `${row.latency_ms} ms` : '—';
    },
  },
];

const fetchTools = async () => {
  loadingTools.value = true;
  try {
    const resp = await api.get('/tools');
    tools.value = resp.data;
  } catch (err: any) {
    message.error('Не удалось загрузить реестр инструментов');
  } finally {
    loadingTools.value = false;
  }
};

const fetchHistory = async () => {
  loadingHistory.value = true;
  try {
    const resp = await api.get('/tools/history?limit=50');
    historyData.value = resp.data;
  } catch (err: any) {
    message.error('Не удалось загрузить историю вызовов');
  } finally {
    loadingHistory.value = false;
  }
};

const openRunModal = (tool: any, dryRun: boolean) => {
  activeTool.value = tool;
  isDryRun.value = dryRun;
  executionResult.value = null;

  // Prefill default sample params
  if (tool.name === 'read.documents.get_unposted') {
    paramsJson.value = JSON.stringify({ doc_type: 'ПлатежноеПоручениеИсходящее', limit: 10 }, null, 2);
  } else if (tool.name === 'read.analytics.get_debtors') {
    paramsJson.value = JSON.stringify({ min_debt: 100000, limit: 10 }, null, 2);
  } else if (tool.name === 'read.warehouse.get_inventory') {
    paramsJson.value = JSON.stringify({ warehouse: 'Центральный склад Алматы', limit: 10 }, null, 2);
  } else {
    paramsJson.value = '{}';
  }

  showRunModal.value = true;
};

const submitExecution = async () => {
  let parsedParams = {};
  try {
    parsedParams = JSON.parse(paramsJson.value || '{}');
  } catch {
    message.error('Невалидный JSON в параметрах');
    return;
  }

  executing.value = true;
  executionResult.value = null;
  try {
    const resp = await api.post('/tools/execute', {
      tool_name: activeTool.value.name,
      params: parsedParams,
      dry_run: isDryRun.value,
    });
    executionResult.value = resp.data;
    message.success(isDryRun.value ? 'Dry-Run успешно завершен' : 'Инструмент успешно выполнен');
    fetchHistory();
  } catch (err: any) {
    const data = err.response?.data;
    const detail = data?.detail;
    let errorCode = data?.error_code;
    let requestId = err.response?.headers?.['x-request-id'] || data?.request_id;
    let msg = '';
    if (typeof detail === 'object' && detail !== null) {
      msg = detail.message || JSON.stringify(detail);
      errorCode = errorCode || detail.error_code;
      requestId = requestId || detail.request_id;
    } else {
      msg = typeof detail === 'string' ? detail : err.message;
    }
    executionResult.value = {
      error: msg,
      error_code: errorCode,
      request_id: requestId,
    };
    message.error('Ошибка выполнения инструмента');
    fetchHistory();
  } finally {
    executing.value = false;
  }
};

onMounted(() => {
  fetchTools();
  fetchHistory();
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

.tool-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.tool-description {
  margin: 0 0 8px 0;
  font-size: 13px;
  color: var(--n-text-color-2);
}

.tool-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}

.result-box {
  background: var(--n-color-embedded);
  padding: 12px;
  border-radius: 6px;
  font-size: 12px;
  max-height: 250px;
  overflow: auto;
  margin: 0;
}
</style>

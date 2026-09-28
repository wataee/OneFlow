<template>
  <div>
    <div class="page-header">
      <div><h1>Daily Guard</h1><p>Ежедневная диагностика данных 1С</p></div>
      <n-button v-if="authStore.user?.role === 'admin'" type="primary" :loading="starting" :disabled="!!activeRun" @click="runScan">Запустить сканирование</n-button>
    </div>
    <n-alert v-if="error" type="error" closable>{{ error }}</n-alert>
    <n-grid :cols="4" :x-gap="12" responsive="screen">
      <n-gi><n-card><n-statistic label="Последнее сканирование" :value="summary?.last_scan ? new Date(summary.last_scan).toLocaleString() : '—'" /></n-card></n-gi>
      <n-gi><n-card><n-statistic label="Ошибки" :value="summary?.errors ?? 0" /></n-card></n-gi>
      <n-gi><n-card><n-statistic label="Предупреждения" :value="summary?.warnings ?? 0" /></n-card></n-gi>
      <n-gi><n-card><n-statistic label="Статус сканирования" :value="activeRun?.status || summary?.status || 'Нет запусков'" /></n-card></n-gi>
    </n-grid>
    <n-card title="Недавние проблемы" class="findings-card">
      <template #header-extra>
        <n-select v-model:value="role" clearable placeholder="Все бизнес-роли" :options="roleOptions" style="width: 210px" @update:value="load" />
      </template>
      <n-spin :show="loading">
        <n-empty v-if="!findings.length" description="Активных проблем нет" />
        <n-list v-else bordered>
          <n-list-item v-for="finding in findings" :key="finding.id">
            <n-thing :title="finding.title" :description="finding.description || finding.rule_code">
              <template #header-extra><n-tag :type="severityType[finding.severity]" size="small">{{ finding.severity }}</n-tag></template>
              <template #footer>{{ finding.business_role }} · {{ finding.rule_code }} · {{ new Date(finding.last_seen_at).toLocaleString() }}</template>
            </n-thing>
          </n-list-item>
        </n-list>
      </n-spin>
    </n-card>
    <n-card v-if="activeRun" title="Сканирование выполняется" class="findings-card">
      {{ activeRun.status }} · Правил: {{ activeRun.rules_completed }}/{{ activeRun.rules_total }}
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue';
import { useMessage } from 'naive-ui';
import { apiClient } from '@/api/client';
import { useAuthStore } from '@/stores/auth';

const message = useMessage();
const authStore = useAuthStore();
const loading = ref(false), starting = ref(false), error = ref('');
const role = ref<string | null>(authStore.user?.business_role || null), findings = ref<any[]>([]), summary = ref<any>(null), activeRun = ref<any>(null);
const roleOptions = ['ACCOUNTANT', 'WAREHOUSE', 'PROCUREMENT', 'MANAGER', 'OWNER'].map(value => ({ label: value, value }));
const severityType: Record<string, any> = { INFO: 'info', WARNING: 'warning', ERROR: 'error', CRITICAL: 'error' };
let timer: ReturnType<typeof setInterval> | undefined;

async function load() {
  loading.value = true; error.value = '';
  try {
    const params: Record<string, string> = {};
    if (role.value) params.business_role = role.value;
    const [s, f, scans] = await Promise.all([
      apiClient.get('/findings/summary', { params }),
      apiClient.get('/findings', { params: { ...params, limit: 50 } }),
      apiClient.get('/scans', { params: { limit: 5 } }),
    ]);
    summary.value = s.data;
    findings.value = f.data.items.filter((item: any) => item.status !== 'RESOLVED');
    activeRun.value = scans.data.items.find((item: any) => ['PENDING', 'RUNNING'].includes(item.status)) || null;
  } catch (e: any) { error.value = e.message || 'Не удалось загрузить Daily Guard'; }
  finally { loading.value = false; }
}

async function runScan() {
  starting.value = true;
  try { const response = await apiClient.post('/scans'); activeRun.value = response.data; message.success('Сканирование поставлено в очередь'); await load(); }
  catch (e: any) { message.error(e.message || 'Не удалось запустить сканирование'); }
  finally { starting.value = false; }
}

onMounted(() => { load(); timer = setInterval(load, 5000); });
onUnmounted(() => { if (timer) clearInterval(timer); });
</script>

<style scoped>
.page-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; }
h1 { margin:0 0 6px; font-size:24px; } p { margin:0; opacity:.65; }
.findings-card { margin-top:18px; }
</style>

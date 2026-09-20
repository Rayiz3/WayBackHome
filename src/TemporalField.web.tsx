import { View, Text } from 'react-native';
import type { TemporalFieldProps } from './TemporalField';
export default function TemporalField(props: TemporalFieldProps) {
  return <View style={{ flex: 1, gap: 8, minWidth: 0 }}>
    <Text style={{ color: '#4a5d4e', fontSize: 12 }}>{props.label}</Text>
    <input aria-label={props.label} type={props.mode} value={props.display} disabled={props.disabled}
      style={{ width: '100%', boxSizing: 'border-box', minWidth: 0, minHeight: 48, padding: 10, border: '1px solid #dce3d7', borderRadius: 10, background: '#fafbf8', color: '#263e2d', fontSize: 15 }}
      onInput={event => {
        if (!event.currentTarget.value) return;
        const date = new Date(props.value);
        const parts = event.currentTarget.value.split(props.mode === 'date' ? '-' : ':').map(Number);
        if (props.mode === 'date') date.setFullYear(parts[0], parts[1] - 1, parts[2]);
        else date.setHours(parts[0], parts[1], 0, 0);
        props.onChange(date);
      }} />
  </View>;
}

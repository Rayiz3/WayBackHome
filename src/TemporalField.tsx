import { useState } from 'react';
import { Platform, Pressable, Text, View } from 'react-native';
import DateTimePicker, { DateTimePickerAndroid } from '@react-native-community/datetimepicker';
export type TemporalFieldProps = { mode: 'date' | 'time'; value: Date; label: string; display: string; disabled: boolean; onChange: (date: Date) => void };
export default function TemporalField(props: TemporalFieldProps) {
  const [open, setOpen] = useState(false);
  function show() {
    if (Platform.OS === 'android') DateTimePickerAndroid.open({
      value: props.value, mode: props.mode, is24Hour: true,
      onValueChange: (_, date) => props.onChange(date),
    });
    else setOpen(true);
  }
  return <View style={{ flex: 1, gap: 8 }}>
    <Text style={{ color: '#4a5d4e', fontSize: 12 }}>{props.label}</Text>
    <Pressable accessibilityRole="button" accessibilityLabel={props.label + ' ' + props.display} disabled={props.disabled} onPress={show}
      style={{ minHeight: 48, padding: 13, borderWidth: 1, borderColor: '#dce3d7', borderRadius: 10, backgroundColor: '#fafbf8' }}>
      <Text style={{ color: '#263e2d', fontSize: 15 }}>{props.display}</Text>
    </Pressable>
    {open && <DateTimePicker value={props.value} mode={props.mode} is24Hour
      onValueChange={(_, date) => { props.onChange(date); setOpen(false); }} onDismiss={() => setOpen(false)} />}
  </View>;
}

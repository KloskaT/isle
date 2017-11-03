mv data/replication_rc_event_schedule.dat data/replication_rc_event_schedule.dat_$(date +%Y_%h_%d_%H_%M)
mv data/replication_randomseed.dat data/replication_randomseed.dat_$(date +%Y_%h_%d_%H_%M)
mv data/two_operational.dat data/two_operational.dat_$(date +%Y_%h_%d_%H_%M)
mv data/two_contracts.dat data/two_contracts.dat_$(date +%Y_%h_%d_%H_%M)
mv data/two_cash.dat data/two_cash.dat_$(date +%Y_%h_%d_%H_%M)
mv data/two_reinoperational.dat data/two_reinoperational.dat_$(date +%Y_%h_%d_%H_%M)
mv data/two_reincontracts.dat data/two_reincontracts.dat_$(date +%Y_%h_%d_%H_%M)
mv data/two_reincash.dat data/two_reincash.dat_$(date +%Y_%h_%d_%H_%M)

for ((i=0; i<3; i++)) do
    #python insurancesimulation.py $i
    python start.py --abce 0 --replicid $i 
done
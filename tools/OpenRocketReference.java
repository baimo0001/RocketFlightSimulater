import java.io.*;
import java.nio.file.*;
import java.util.*;
import net.sf.openrocket.utils.BasicApplication;
import net.sf.openrocket.rocketcomponent.*;
import net.sf.openrocket.rocketcomponent.position.AxialMethod;
import net.sf.openrocket.motor.*;
import net.sf.openrocket.util.*;
import net.sf.openrocket.document.*;
import net.sf.openrocket.simulation.*;
import net.sf.openrocket.simulation.listeners.*;
import net.sf.openrocket.aerodynamics.*;
import net.sf.openrocket.logging.*;
import net.sf.openrocket.file.openrocket.OpenRocketSaver;

/** Runs the locally installed OpenRocket engine for comparison. */
public class OpenRocketReference {
    static Properties p;
    static double n(String key) { return Double.parseDouble(p.getProperty(key)); }
    static double[] array(String key) { return Arrays.stream(p.getProperty(key).split(",")).mapToDouble(Double::parseDouble).toArray(); }
    static void mass(RocketComponent c, double m, double x) {
        c.setMassOverridden(true); c.setOverrideMass(m);
        c.setCGOverridden(true); c.setOverrideCGX(x);
    }
    public static void main(String[] args) throws Exception {
        Locale.setDefault(Locale.US);
        new BasicApplication().initializeApplication();
        p=new Properties();
        try(Reader r=Files.newBufferedReader(Paths.get(args[0]))) { p.load(r); }
        Path output=Paths.get(args[1]); Files.createDirectories(output);
        Rocket rocket=new Rocket();rocket.setName(p.getProperty("name"));
        AxialStage stage=new AxialStage();rocket.addChild(stage);
        NoseCone nose=new NoseCone(Transition.Shape.CONICAL,n("nose"),n("diameter")/2);
        stage.addChild(nose);mass(nose,0,0);
        BodyTube tube=new BodyTube(n("length")-n("nose"),n("diameter")/2,.001);
        stage.addChild(tube);mass(tube,n("airframe_mass"),n("airframe_cg")-n("nose"));
        TrapezoidFinSet fins=new TrapezoidFinSet();tube.addChild(fins);
        fins.setFinCount((int)n("fin_count"));fins.setRootChord(n("fin_root"));fins.setTipChord(n("fin_tip"));
        fins.setHeight(n("fin_span"));fins.setSweep(n("fin_sweep"));fins.setThickness(.001);
        fins.setAxialMethod(AxialMethod.TOP);fins.setAxialOffset(n("fin_position")-n("nose"));mass(fins,0,0);
        tube.setMotorMount(true);tube.setMotorOverhang(n("motor_position")-n("length")+.05);
        double[] times=array("times"),forces=array("forces"),remaining=array("remaining");
        Coordinate[] cg=new Coordinate[times.length];
        for(int i=0;i<cg.length;i++) cg[i]=new Coordinate(.05,0,0,n("motor_dry")+remaining[i]);
        ThrustCurveMotor motor=new ThrustCurveMotor.Builder()
            .setManufacturer(Manufacturer.getManufacturer("Nebula validation"))
            .setDesignation("Teaching curve").setDescription("Synthetic validation data")
            .setMotorType(Motor.Type.SINGLE).setDiameter(.024).setLength(.1)
            .setTimePoints(times).setThrustPoints(forces).setCGPoints(cg)
            .setStandardDelays(new double[]{0}).setDigest("nebula-validation").build();
        FlightConfigurationId id=new FlightConfigurationId();
        rocket.createFlightConfiguration(id);rocket.setSelectedConfiguration(id);
        MotorConfiguration mc=new MotorConfiguration(tube,id);mc.setMotor(motor);
        mc.setIgnitionEvent(IgnitionEvent.LAUNCH);mc.setEjectionDelay(Double.POSITIVE_INFINITY);
        tube.setMotorConfig(mc,id);rocket.getSelectedConfiguration().update();
        rocket.enableEvents();rocket.update();
        Simulation sim=new Simulation(rocket);sim.setFlightConfigurationId(id);sim.setName(p.getProperty("name"));
        SimulationOptions options=sim.getOptions();
        options.setLaunchRodLength(n("rail"));options.setLaunchRodAngle(0);options.setLaunchIntoWind(false);
        options.setWindSpeedAverage(0);options.setWindSpeedDeviation(0);options.setWindTurbulenceIntensity(0);
        options.setLaunchAltitude(n("altitude"));options.setISAAtmosphere(true);
        options.setGeodeticComputation(GeodeticComputationStrategy.FLAT);options.setTimeStep(.002);
        options.setRandomSeed(12345);
        final boolean matched=p.getProperty("matched").equals("true");
        AbstractSimulationListener listener=new AbstractSimulationListener() {
            public double preGravityModel(SimulationStatus status) { return 9.80665; }
            public Coordinate preWindModel(SimulationStatus status) { return Coordinate.ZERO; }
            public AerodynamicForces postAerodynamicCalculation(SimulationStatus status,AerodynamicForces f) {
                if(matched) {
                    f.setCD(n("cd"));f.setCDaxial(n("cd"));
                    f.setCN(0);f.setCm(0);f.setCside(0);f.setCyaw(0);
                    f.setCroll(0);f.setCrollDamp(0);f.setCrollForce(0);
                }
                return f;
            }
        };
        sim.simulate(listener);
        FlightData data=sim.getSimulatedData();FlightDataBranch branch=data.getBranch(0);
        FlightConditions fc=new FlightConditions(rocket.getSelectedConfiguration());fc.setMach(0);fc.setAOA(0);
        double cp=new BarrowmanCalculator().getCP(rocket.getSelectedConfiguration(),fc,new WarningSet()).x;
        try(PrintWriter out=new PrintWriter(Files.newBufferedWriter(output.resolve("summary.csv")))) {
            out.println("apogee_m,max_ascent_speed_m_s,initial_mass_kg,initial_cg_m,cp_m,total_impulse_ns,burn_time_s,launch_rod_speed_m_s");
            out.printf("%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g%n",data.getMaxAltitude(),
                branch.getMaximum(FlightDataType.TYPE_VELOCITY_Z),branch.getByIndex(FlightDataType.TYPE_MASS,0),
                branch.getByIndex(FlightDataType.TYPE_CG_LOCATION,0),cp,motor.getTotalImpulseEstimate(),
                motor.getBurnTime(),data.getLaunchRodVelocity());
        }
        FlightDataType[] types={FlightDataType.TYPE_TIME,FlightDataType.TYPE_ALTITUDE,FlightDataType.TYPE_VELOCITY_Z,
            FlightDataType.TYPE_MASS,FlightDataType.TYPE_CG_LOCATION,FlightDataType.TYPE_CP_LOCATION,
            FlightDataType.TYPE_THRUST_FORCE,FlightDataType.TYPE_DRAG_COEFF,FlightDataType.TYPE_GRAVITY};
        try(PrintWriter out=new PrintWriter(Files.newBufferedWriter(output.resolve("trajectory.csv")))) {
            out.println("time_s,altitude_m,velocity_m_s,mass_kg,cg_m,cp_m,thrust_n,cd,gravity_m_s2");
            for(int i=0;i<branch.getLength();i++) {
                for(int j=0;j<types.length;j++) { if(j>0)out.print(',');out.print(branch.getByIndex(types[j],i)); }
                out.println();
            }
        }
        try(PrintWriter out=new PrintWriter(Files.newBufferedWriter(output.resolve("events.csv")))) {
            out.println("event,time_s");
            for(FlightEvent e:branch.getEvents()) out.println(e.getType().name()+","+e.getTime());
        }
        OpenRocketDocument doc=OpenRocketDocumentFactory.createDocumentFromRocket(rocket);
        StorageOptions storage=new StorageOptions();storage.setSaveSimulationData(false);
        try(OutputStream stream=Files.newOutputStream(output.resolve("reference.ork"))) {
            new OpenRocketSaver().save(stream,doc,storage,new WarningSet(),new ErrorSet());
        }
        Files.writeString(output.resolve("warnings.txt"),data.getWarningSet().toString());
        System.out.println("OPENROCKET_OK "+p.getProperty("name")+" altitude="+data.getMaxAltitude());
    }
}
